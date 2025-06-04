#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#define MAX_BLK (1024u * 100u)

typedef enum {
    COPY = 0,
    INSERT,
    NU_OP
} operation_t;

typedef struct {
    FILE *f;
    size_t total_size;
} file_info_t;

typedef struct {
    uint32_t orig_pos;
    uint32_t size;
} copy_data_t;

typedef struct {
    uint32_t final_pos;
    uint32_t size;
    uint8_t *block;
} insert_data_t;

typedef struct file_block_t {
    operation_t type;
    void *data;
    struct file_block_t *prev;
    struct file_block_t *next;
} file_block_t;

static void file_info_init(file_info_t *info, FILE *f) {
    fseek(f, 0, SEEK_END);
    info->total_size = (size_t)ftell(f);
    fseek(f, 0, SEEK_SET);
    info->f = f;
}

static file_block_t *new_file_block(file_block_t *prev) {
    file_block_t *fb = calloc(1, sizeof(*fb));
    if (!fb) return NULL;
    fb->prev = prev;
    if (prev) prev->next = fb;
    fb->type = NU_OP;
    return fb;
}

static file_block_t *make_insert_block(file_block_t *tail, const uint8_t *buf, uint32_t pos, uint32_t sz) {
    file_block_t *fb = new_file_block(tail);
    if (!fb) return NULL;
    insert_data_t *id = malloc(sizeof(*id));
    if (!id) { free(fb); return NULL; }
    id->block = malloc(sz);
    if (!id->block) { free(id); free(fb); return NULL; }
    memcpy(id->block, buf, sz);
    id->size = sz;
    id->final_pos = pos;
    fb->type = INSERT;
    fb->data = id;
    return fb;
}

static file_block_t *make_copy_block(file_block_t *tail, uint32_t pos, uint32_t sz) {
    file_block_t *fb = new_file_block(tail);
    if (!fb) return NULL;
    copy_data_t *cd = malloc(sizeof(*cd));
    if (!cd) { free(fb); return NULL; }
    cd->orig_pos = pos;
    cd->size = sz;
    fb->type = COPY;
    fb->data = cd;
    return fb;
}

static void emit_blocks(file_block_t *tail, FILE *out) {
    /* move to first block */
    while (tail && tail->prev) tail = tail->prev;
    while (tail) {
        if (tail->type == COPY) {
            copy_data_t *cd = tail->data;
            fwrite(&tail->type, sizeof(uint32_t), 1, out);
            fwrite(&cd->orig_pos, sizeof(cd->orig_pos), 1, out);
            fwrite(&cd->size, sizeof(cd->size), 1, out);
        } else if (tail->type == INSERT) {
            insert_data_t *id = tail->data;
            fwrite(&tail->type, sizeof(uint32_t), 1, out);
            fwrite(&id->final_pos, sizeof(id->final_pos), 1, out);
            fwrite(&id->size, sizeof(id->size), 1, out);
            fwrite(id->block, 1, id->size, out);
        }
        tail = tail->next;
    }
}

static void free_blocks(file_block_t *tail) {
    while (tail && tail->prev) tail = tail->prev;
    while (tail) {
        file_block_t *next = tail->next;
        if (tail->type == INSERT) {
            insert_data_t *id = tail->data;
            free(id->block);
            free(id);
        } else if (tail->type == COPY) {
            free(tail->data);
        }
        free(tail);
        tail = next;
    }
}

static void find_matches(const file_info_t *orig, const file_info_t *fin,
                         const uint8_t *buf_orig, const uint8_t *buf_fin,
                         FILE *out) {
    size_t last_pos = 0;
    file_block_t *tail = NULL;
    size_t total_saved = 0;
    size_t total = 0;

    for (size_t idx_final = 0; idx_final < fin->total_size;) {
        size_t best_final = 0;
        size_t best_orig = 0;
        size_t best_len = 0;
        for (size_t idx_orig = 0; idx_orig < orig->total_size; idx_orig += 4) {
            for (size_t z = 4; z < MAX_BLK; z += 4) {
                if (idx_orig + z > orig->total_size || idx_final + z > fin->total_size)
                    break;
                if (memcmp(&buf_orig[idx_orig], &buf_fin[idx_final], z) != 0)
                    break;
                if (z > best_len) {
                    best_final = idx_final;
                    best_orig = idx_orig;
                    best_len = z;
                }
            }
        }

        if (best_len > 0) {
            if (best_len > 12) {
                if (last_pos != best_final) {
                    tail = make_insert_block(tail, &buf_fin[last_pos], (uint32_t)last_pos,
                                             (uint32_t)(best_final - last_pos));
                    total += best_final - last_pos;
                }
                tail = make_copy_block(tail, (uint32_t)best_orig, (uint32_t)best_len);
                total_saved += best_len;
                total += best_len;
                last_pos = best_final + best_len;
            }
            idx_final += best_len;
        } else {
            idx_final += 4;
        }
    }

    if (total < fin->total_size) {
        tail = make_insert_block(tail, &buf_fin[total], (uint32_t)total,
                                 (uint32_t)(fin->total_size - total));
    }

    printf("Total: %zu, igual: %zu, ratio: %f\n", fin->total_size, total_saved,
           1.0 - (double)total_saved / fin->total_size);

    if (tail) emit_blocks(tail, out);
    free_blocks(tail);
}

int main(int argc, char *argv[]) {
    if (argc < 4) {
        fprintf(stderr, "Usage: %s <old file> <new file> <delta file>\n", argv[0]);
        return EXIT_FAILURE;
    }

    FILE *f_orig = fopen(argv[1], "rb");
    if (!f_orig) {
        perror("open old file");
        return EXIT_FAILURE;
    }
    FILE *f_new = fopen(argv[2], "rb");
    if (!f_new) {
        perror("open new file");
        fclose(f_orig);
        return EXIT_FAILURE;
    }
    FILE *f_patch = fopen(argv[3], "wb");
    if (!f_patch) {
        perror("open patch file");
        fclose(f_orig);
        fclose(f_new);
        return EXIT_FAILURE;
    }

    file_info_t info_orig, info_new;
    file_info_init(&info_orig, f_orig);
    file_info_init(&info_new, f_new);

    uint8_t *buf_orig = malloc(info_orig.total_size);
    uint8_t *buf_new = malloc(info_new.total_size);
    if (!buf_orig || !buf_new) {
        fprintf(stderr, "memory allocation failed\n");
        free(buf_orig);
        free(buf_new);
        fclose(f_patch);
        fclose(f_new);
        fclose(f_orig);
        return EXIT_FAILURE;
    }

    fread(buf_orig, 1, info_orig.total_size, f_orig);
    fread(buf_new, 1, info_new.total_size, f_new);

    find_matches(&info_orig, &info_new, buf_orig, buf_new, f_patch);

    free(buf_orig);
    free(buf_new);
    fclose(f_patch);
    fclose(f_new);
    fclose(f_orig);
    return EXIT_SUCCESS;
}


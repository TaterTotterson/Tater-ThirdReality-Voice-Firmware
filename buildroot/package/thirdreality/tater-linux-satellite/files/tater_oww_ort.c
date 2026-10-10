/*
 * Stateful openWakeWord ONNX scorer for Tater's ARM64 Linux satellites.
 *
 * The audio/feature contract intentionally matches the Echo firmware: one
 * 16 kHz mono stream, 80 ms inference steps, and the upstream openWakeWord
 * melspectrogram and embedding models.  ONNX Runtime is loaded dynamically so
 * an MWW-only satellite can still start if the optional runtime is damaged.
 */

#include <dlfcn.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "onnxruntime_c_api.h"

#define OWW_CHUNK_SAMPLES 1280
#define OWW_CONTEXT_SAMPLES 480
#define OWW_MEL_BINS 32
#define OWW_MEL_WINDOW 76
#define OWW_MEL_RING_FRAMES 970
#define OWW_FEATURE_DIM 96
#define OWW_FEATURE_WINDOW 16
#define OWW_FEATURE_RING 120

typedef const OrtApiBase *(*ort_get_api_base_fn)(void);

typedef struct {
    const OrtApi *api;
    OrtSession *session;
    char *input_name;
    char *output_name;
} tater_model;

typedef struct {
    void *dl;
    const OrtApi *api;
    OrtEnv *env;
    tater_model mel_model;
    tater_model embedding_model;
    tater_model classifier_model;
    int16_t pending[OWW_CHUNK_SAMPLES * 2];
    size_t pending_count;
    int16_t context[OWW_CONTEXT_SAMPLES];
    size_t context_count;
    float mel[OWW_MEL_RING_FRAMES * OWW_MEL_BINS];
    size_t mel_count;
    float features[OWW_FEATURE_RING * OWW_FEATURE_DIM];
    size_t feature_count;
    float mel_window[OWW_MEL_WINDOW * OWW_MEL_BINS];
    char version[64];
} tater_oww_engine;

static char *duplicate_text(const char *text) {
    size_t size = strlen(text) + 1;
    char *copy = (char *)malloc(size);
    if (copy != NULL) memcpy(copy, text, size);
    return copy;
}

static char *ort_error(const OrtApi *api, OrtStatus *status) {
    if (status == NULL) return NULL;
    char *message = duplicate_text(api->GetErrorMessage(status));
    api->ReleaseStatus(status);
    return message != NULL ? message : duplicate_text("onnxruntime error");
}

static void model_close(tater_model *model) {
    const OrtApi *api = model->api;
    if (api == NULL) return;
    if (model->session != NULL) api->ReleaseSession(model->session);
    OrtAllocator *allocator = NULL;
    OrtStatus *status = api->GetAllocatorWithDefaultOptions(&allocator);
    if (status == NULL) {
        if (model->input_name != NULL) {
            status = api->AllocatorFree(allocator, model->input_name);
            if (status != NULL) api->ReleaseStatus(status);
        }
        if (model->output_name != NULL) {
            status = api->AllocatorFree(allocator, model->output_name);
            if (status != NULL) api->ReleaseStatus(status);
        }
    } else {
        api->ReleaseStatus(status);
    }
    memset(model, 0, sizeof(*model));
}

static char *model_open(tater_oww_engine *engine, const char *path, tater_model *model) {
    const OrtApi *api = engine->api;
    memset(model, 0, sizeof(*model));
    model->api = api;
    OrtSessionOptions *options = NULL;
    char *error = ort_error(api, api->CreateSessionOptions(&options));
    if (error != NULL) return error;
    if ((error = ort_error(api, api->SetIntraOpNumThreads(options, 1))) != NULL ||
        (error = ort_error(api, api->SetInterOpNumThreads(options, 1))) != NULL ||
        (error = ort_error(api, api->SetSessionExecutionMode(options, ORT_SEQUENTIAL))) != NULL ||
        (error = ort_error(api, api->SetSessionGraphOptimizationLevel(options, ORT_ENABLE_ALL))) != NULL) {
        api->ReleaseSessionOptions(options);
        return error;
    }
    const char *off = "0";
    if ((error = ort_error(api, api->AddSessionConfigEntry(
             options, "session.intra_op.allow_spinning", off))) != NULL ||
        (error = ort_error(api, api->AddSessionConfigEntry(
             options, "session.inter_op.allow_spinning", off))) != NULL) {
        api->ReleaseSessionOptions(options);
        return error;
    }
    error = ort_error(api, api->CreateSession(engine->env, path, options, &model->session));
    api->ReleaseSessionOptions(options);
    if (error != NULL) return error;

    OrtAllocator *allocator = NULL;
    if ((error = ort_error(api, api->GetAllocatorWithDefaultOptions(&allocator))) != NULL ||
        (error = ort_error(api, api->SessionGetInputName(
             model->session, 0, allocator, &model->input_name))) != NULL ||
        (error = ort_error(api, api->SessionGetOutputName(
             model->session, 0, allocator, &model->output_name))) != NULL) {
        model_close(model);
        return error;
    }
    return NULL;
}

static char *model_run(tater_model *model, const float *input_data, size_t input_count,
                       const int64_t *shape, size_t dimensions,
                       float **output_data, size_t *output_count) {
    const OrtApi *api = model->api;
    *output_data = NULL;
    *output_count = 0;
    OrtMemoryInfo *memory = NULL;
    char *error = ort_error(api, api->CreateCpuMemoryInfo(
        OrtArenaAllocator, OrtMemTypeDefault, &memory));
    if (error != NULL) return error;
    OrtValue *input = NULL;
    OrtValue *output = NULL;
    error = ort_error(api, api->CreateTensorWithDataAsOrtValue(
        memory, (void *)input_data, input_count * sizeof(float), shape, dimensions,
        ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT, &input));
    api->ReleaseMemoryInfo(memory);
    if (error != NULL) return error;
    error = ort_error(api, api->Run(
        model->session, NULL,
        (const char *const *)&model->input_name, (const OrtValue *const *)&input, 1,
        (const char *const *)&model->output_name, 1, &output));
    api->ReleaseValue(input);
    if (error != NULL) return error;
    OrtTensorTypeAndShapeInfo *tensor_info = NULL;
    if ((error = ort_error(api, api->GetTensorTypeAndShape(output, &tensor_info))) != NULL) {
        api->ReleaseValue(output);
        return error;
    }
    size_t count = 0;
    error = ort_error(api, api->GetTensorShapeElementCount(tensor_info, &count));
    api->ReleaseTensorTypeAndShapeInfo(tensor_info);
    if (error != NULL) {
        api->ReleaseValue(output);
        return error;
    }
    float *source = NULL;
    if ((error = ort_error(api, api->GetTensorMutableData(output, (void **)&source))) != NULL) {
        api->ReleaseValue(output);
        return error;
    }
    float *copy = (float *)malloc(count * sizeof(float));
    if (copy == NULL) {
        api->ReleaseValue(output);
        return duplicate_text("out of memory copying ONNX output");
    }
    memcpy(copy, source, count * sizeof(float));
    api->ReleaseValue(output);
    *output_data = copy;
    *output_count = count;
    return NULL;
}

static void append_ring(float *ring, size_t *count, size_t capacity,
                        const float *values, size_t value_count) {
    if (value_count >= capacity) {
        memcpy(ring, values + value_count - capacity, capacity * sizeof(float));
        *count = capacity;
        return;
    }
    if (*count + value_count > capacity) {
        size_t discard = *count + value_count - capacity;
        memmove(ring, ring + discard, (*count - discard) * sizeof(float));
        *count -= discard;
    }
    memcpy(ring + *count, values, value_count * sizeof(float));
    *count += value_count;
}

static char *process_chunk(tater_oww_engine *engine, const int16_t *chunk,
                           float *score, int *ready) {
    size_t input_count = engine->context_count + OWW_CHUNK_SAMPLES;
    float *input = (float *)malloc(input_count * sizeof(float));
    if (input == NULL) return duplicate_text("out of memory preparing OWW audio");
    for (size_t i = 0; i < engine->context_count; ++i) input[i] = engine->context[i];
    for (size_t i = 0; i < OWW_CHUNK_SAMPLES; ++i) input[engine->context_count + i] = chunk[i];

    int64_t mel_shape[2] = {1, (int64_t)input_count};
    float *mel_output = NULL;
    size_t mel_count = 0;
    char *error = model_run(&engine->mel_model, input, input_count, mel_shape, 2,
                            &mel_output, &mel_count);
    free(input);
    if (error != NULL) return error;
    if (mel_count == 0 || mel_count % OWW_MEL_BINS != 0) {
        free(mel_output);
        return duplicate_text("openWakeWord melspectrogram shape mismatch");
    }
    for (size_t i = 0; i < mel_count; ++i) mel_output[i] = mel_output[i] / 10.0f + 2.0f;
    append_ring(engine->mel, &engine->mel_count,
                OWW_MEL_RING_FRAMES * OWW_MEL_BINS, mel_output, mel_count);
    free(mel_output);
    if (engine->mel_count < OWW_MEL_WINDOW * OWW_MEL_BINS) {
        return duplicate_text("openWakeWord mel warm-up invariant failed");
    }
    memcpy(engine->mel_window,
           engine->mel + engine->mel_count - OWW_MEL_WINDOW * OWW_MEL_BINS,
           sizeof(engine->mel_window));

    int64_t embedding_shape[4] = {1, OWW_MEL_WINDOW, OWW_MEL_BINS, 1};
    float *embedding = NULL;
    size_t embedding_count = 0;
    error = model_run(&engine->embedding_model, engine->mel_window,
                      OWW_MEL_WINDOW * OWW_MEL_BINS, embedding_shape, 4,
                      &embedding, &embedding_count);
    if (error != NULL) return error;
    if (embedding_count != OWW_FEATURE_DIM) {
        free(embedding);
        return duplicate_text("openWakeWord embedding shape mismatch");
    }
    append_ring(engine->features, &engine->feature_count,
                OWW_FEATURE_RING * OWW_FEATURE_DIM, embedding, embedding_count);
    free(embedding);

    const int16_t *context_source = chunk + OWW_CHUNK_SAMPLES - OWW_CONTEXT_SAMPLES;
    memcpy(engine->context, context_source, sizeof(engine->context));
    engine->context_count = OWW_CONTEXT_SAMPLES;
    if (engine->feature_count < OWW_FEATURE_WINDOW * OWW_FEATURE_DIM) {
        *ready = 0;
        return NULL;
    }
    int64_t classifier_shape[3] = {1, OWW_FEATURE_WINDOW, OWW_FEATURE_DIM};
    float *classifier = NULL;
    size_t classifier_count = 0;
    error = model_run(
        &engine->classifier_model,
        engine->features + engine->feature_count - OWW_FEATURE_WINDOW * OWW_FEATURE_DIM,
        OWW_FEATURE_WINDOW * OWW_FEATURE_DIM, classifier_shape, 3,
        &classifier, &classifier_count);
    if (error != NULL) return error;
    if (classifier_count != 1 || !isfinite(classifier[0]) ||
        classifier[0] < 0.0f || classifier[0] > 1.0f) {
        free(classifier);
        return duplicate_text("openWakeWord classifier output is invalid");
    }
    *score = classifier[0];
    *ready = 1;
    free(classifier);
    return NULL;
}

void tater_oww_free_error(char *message) { free(message); }

void *tater_oww_create(const char *runtime_path, const char *mel_path,
                       const char *embedding_path, const char *classifier_path,
                       char **error_out) {
    *error_out = NULL;
    tater_oww_engine *engine = (tater_oww_engine *)calloc(1, sizeof(*engine));
    if (engine == NULL) {
        *error_out = duplicate_text("out of memory creating OWW engine");
        return NULL;
    }
    engine->dl = dlopen(runtime_path, RTLD_NOW | RTLD_LOCAL);
    if (engine->dl == NULL) {
        const char *message = dlerror();
        *error_out = duplicate_text(message != NULL ? message : "dlopen failed");
        free(engine);
        return NULL;
    }
    ort_get_api_base_fn get_base = (ort_get_api_base_fn)dlsym(engine->dl, "OrtGetApiBase");
    if (get_base == NULL) {
        *error_out = duplicate_text("OrtGetApiBase not found");
        dlclose(engine->dl);
        free(engine);
        return NULL;
    }
    const OrtApiBase *base = get_base();
    engine->api = base != NULL ? base->GetApi(ORT_API_VERSION) : NULL;
    if (engine->api == NULL) {
        *error_out = duplicate_text("incompatible ONNX Runtime C API");
        dlclose(engine->dl);
        free(engine);
        return NULL;
    }
    snprintf(engine->version, sizeof(engine->version), "%s", base->GetVersionString());
    if ((*error_out = ort_error(engine->api, engine->api->CreateEnv(
             ORT_LOGGING_LEVEL_ERROR, "tater-s420-oww", &engine->env))) != NULL ||
        (*error_out = model_open(engine, mel_path, &engine->mel_model)) != NULL ||
        (*error_out = model_open(engine, embedding_path, &engine->embedding_model)) != NULL ||
        (*error_out = model_open(engine, classifier_path, &engine->classifier_model)) != NULL) {
        model_close(&engine->classifier_model);
        model_close(&engine->embedding_model);
        model_close(&engine->mel_model);
        if (engine->env != NULL) engine->api->ReleaseEnv(engine->env);
        dlclose(engine->dl);
        free(engine);
        return NULL;
    }
    engine->mel_count = OWW_MEL_WINDOW * OWW_MEL_BINS;
    for (size_t i = 0; i < engine->mel_count; ++i) engine->mel[i] = 1.0f;
    return engine;
}

const char *tater_oww_version(void *opaque) {
    tater_oww_engine *engine = (tater_oww_engine *)opaque;
    return engine != NULL ? engine->version : "";
}

void tater_oww_reset(void *opaque) {
    tater_oww_engine *engine = (tater_oww_engine *)opaque;
    if (engine == NULL) return;
    engine->pending_count = 0;
    engine->context_count = 0;
    engine->feature_count = 0;
    engine->mel_count = OWW_MEL_WINDOW * OWW_MEL_BINS;
    for (size_t i = 0; i < engine->mel_count; ++i) engine->mel[i] = 1.0f;
}

int tater_oww_push(void *opaque, const int16_t *samples, size_t sample_count,
                   float *scores, size_t score_capacity, size_t *score_count,
                   char **error_out) {
    tater_oww_engine *engine = (tater_oww_engine *)opaque;
    *score_count = 0;
    *error_out = NULL;
    if (engine == NULL || samples == NULL) {
        *error_out = duplicate_text("invalid openWakeWord engine or audio");
        return 0;
    }
    size_t offset = 0;
    while (offset < sample_count) {
        size_t room = sizeof(engine->pending) / sizeof(engine->pending[0]) - engine->pending_count;
        if (room == 0) {
            *error_out = duplicate_text("openWakeWord pending audio overflow");
            return 0;
        }
        size_t take = sample_count - offset < room ? sample_count - offset : room;
        memcpy(engine->pending + engine->pending_count, samples + offset, take * sizeof(int16_t));
        engine->pending_count += take;
        offset += take;
        while (engine->pending_count >= OWW_CHUNK_SAMPLES) {
            float score = 0.0f;
            int ready = 0;
            char *error = process_chunk(engine, engine->pending, &score, &ready);
            memmove(engine->pending, engine->pending + OWW_CHUNK_SAMPLES,
                    (engine->pending_count - OWW_CHUNK_SAMPLES) * sizeof(int16_t));
            engine->pending_count -= OWW_CHUNK_SAMPLES;
            if (error != NULL) {
                *error_out = error;
                return 0;
            }
            if (ready) {
                if (*score_count >= score_capacity) {
                    *error_out = duplicate_text("openWakeWord score output overflow");
                    return 0;
                }
                scores[(*score_count)++] = score;
            }
        }
    }
    return 1;
}

void tater_oww_destroy(void *opaque) {
    tater_oww_engine *engine = (tater_oww_engine *)opaque;
    if (engine == NULL) return;
    model_close(&engine->classifier_model);
    model_close(&engine->embedding_model);
    model_close(&engine->mel_model);
    if (engine->env != NULL) engine->api->ReleaseEnv(engine->env);
    if (engine->dl != NULL) dlclose(engine->dl);
    free(engine);
}

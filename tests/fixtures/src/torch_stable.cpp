/* Tiny extension that talks to libtorch through the stable C shim only. */
#include <torch/csrc/inductor/aoti_torch/c/shim.h>

#include "fixture_export.h"

extern "C" FIXTURE_EXPORT int fixture_get_dim(AtenTensorHandle t, int64_t *out) {
    return aoti_torch_get_dim(t, out);
}

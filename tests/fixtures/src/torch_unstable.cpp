/* Tiny extension that intentionally uses unstable libtorch APIs. */
#include <ATen/Tensor.h>
#include <c10/core/Device.h>

extern "C" int64_t fixture_numel(at::Tensor *t) {
    return t->numel();
}

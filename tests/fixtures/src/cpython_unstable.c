/* Tiny CPython extension that intentionally uses non-limited-API symbols. */
#include <Python.h>

static PyObject *touch_internal(PyObject *self, PyObject *args) {
    (void)self; (void)args;
    /* _PyArg_CheckPositional is private and not part of the stable ABI. */
    if (!_PyArg_CheckPositional("touch", PyTuple_GET_SIZE(args), 0, 0)) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyMethodDef Methods[] = {
    {"touch_internal", touch_internal, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT, "fixture_unstable", NULL, -1, Methods,
    NULL, NULL, NULL, NULL,
};

PyMODINIT_FUNC PyInit_fixture_unstable(void) {
    return PyModule_Create(&moduledef);
}

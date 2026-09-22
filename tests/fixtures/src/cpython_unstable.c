/* Tiny CPython extension that intentionally uses non-limited-API symbols. */
#include <Python.h>

static PyObject *touch_internal(PyObject *self, PyObject *args) {
    (void)self; (void)args;
    /* Private, non-stable API available across the tested Python versions. */
    return _PyDict_NewPresized(0);
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

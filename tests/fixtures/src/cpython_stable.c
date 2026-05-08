/* Tiny CPython extension built against the limited API. */
#define Py_LIMITED_API 0x030B0000
#include <Python.h>

static PyObject *hello(PyObject *self, PyObject *args) {
    (void)self; (void)args;
    return PyUnicode_FromString("hello");
}

static PyMethodDef Methods[] = {
    {"hello", hello, METH_NOARGS, "say hello"},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT, "fixture_stable", NULL, -1, Methods,
    NULL, NULL, NULL, NULL,
};

PyMODINIT_FUNC PyInit_fixture_stable(void) {
    return PyModule_Create(&moduledef);
}

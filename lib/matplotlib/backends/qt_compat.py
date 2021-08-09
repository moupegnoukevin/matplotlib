"""
Qt binding and backend selector.

The selection logic is as follows:
- if any of PyQt6, PySide6, PyQt5, or PySide2 have already been
  imported (checked in that order), use it;
- otherwise, if the QT_API environment variable (used by Enthought) is set, use
  it to determine which binding to use (but do not change the backend based on
  it; i.e. if the Qt5Agg backend is requested but QT_API is set to "pyqt4",
  then actually use Qt5 with PyQt5 or PySide2 (whichever can be imported);
- otherwise, use whatever the rcParams indicate.
"""

import functools
import operator
import os
import platform
import sys

from packaging.version import parse as parse_version

import matplotlib as mpl


QT_API_PYQT6 = "PyQt6"
QT_API_PYSIDE6 = "PySide6"
QT_API_PYQT5 = "PyQt5"
QT_API_PYSIDE2 = "PySide2"
QT_API_PYQTv2 = "PyQt4v2"
QT_API_PYSIDE = "PySide"
QT_API_PYQT = "PyQt4"   # Use the old sip v1 API (Py3 defaults to v2).
QT_API_ENV = os.environ.get("QT_API")
if QT_API_ENV is not None:
    QT_API_ENV = QT_API_ENV.lower()
# Mapping of QT_API_ENV to requested binding.  ETS does not support PyQt4v1.
# (https://github.com/enthought/pyface/blob/master/pyface/qt/__init__.py)
_ETS = {
    "pyqt6": QT_API_PYQT6, "pyside6": QT_API_PYSIDE6,
    "pyqt5": QT_API_PYQT5, "pyside2": QT_API_PYSIDE2,
    None: None
}
# First, check if anything is already imported.
if sys.modules.get("PyQt6.QtCore"):
    QT_API = QT_API_PYQT6
elif sys.modules.get("PySide6.QtCore"):
    QT_API = QT_API_PYSIDE6
elif sys.modules.get("PyQt5.QtCore"):
    QT_API = QT_API_PYQT5
elif sys.modules.get("PySide2.QtCore"):
    QT_API = QT_API_PYSIDE2
# Otherwise, check the QT_API environment variable (from Enthought).  This can
# only override the binding, not the backend (in other words, we check that the
# requested backend actually matches).  Use dict.__getitem__ to avoid
# triggering backend resolution (which can result in a partially but
# incompletely imported backend_qt5).
elif dict.__getitem__(mpl.rcParams, "backend") in ["Qt5Agg", "Qt5Cairo"]:
    if QT_API_ENV in ["pyqt5", "pyside2"]:
        QT_API = _ETS[QT_API_ENV]
    else:
        QT_API = None
# A non-Qt backend was selected but we still got there (possible, e.g., when
# fully manually embedding Matplotlib in a Qt app without using pyplot).
elif QT_API_ENV is None:
    QT_API = None
else:
    try:
        QT_API = _ETS[QT_API_ENV]
    except KeyError as err:
        raise RuntimeError(
            "The environment variable QT_API has the unrecognized value "
            f"{QT_API_ENV!r}; "
            f"valid values are {set(k for k in _ETS if k is not None)}"
        ) from None


def _setup_pyqt5plus():
    global QtCore, QtGui, QtWidgets, __version__, is_pyqt5, \
        _isdeleted, _getSaveFileName

    if QT_API == QT_API_PYQT6:
        from PyQt6 import QtCore, QtGui, QtWidgets, sip
        __version__ = QtCore.PYQT_VERSION_STR
        QtCore.Signal = QtCore.pyqtSignal
        QtCore.Slot = QtCore.pyqtSlot
        QtCore.Property = QtCore.pyqtProperty
        _isdeleted = sip.isdeleted
    elif QT_API == QT_API_PYSIDE6:
        from PySide6 import QtCore, QtGui, QtWidgets, __version__
        import shiboken6
        def _isdeleted(obj): return not shiboken6.isValid(obj)
    elif QT_API == QT_API_PYQT5:
        from PyQt5 import QtCore, QtGui, QtWidgets
        import sip
        __version__ = QtCore.PYQT_VERSION_STR
        QtCore.Signal = QtCore.pyqtSignal
        QtCore.Slot = QtCore.pyqtSlot
        QtCore.Property = QtCore.pyqtProperty
        _isdeleted = sip.isdeleted
    elif QT_API == QT_API_PYSIDE2:
        from PySide2 import QtCore, QtGui, QtWidgets, __version__
        import shiboken2
        def _isdeleted(obj): return not shiboken2.isValid(obj)
    else:
        raise AssertionError(f"Unexpected QT_API: {QT_API}")
    _getSaveFileName = QtWidgets.QFileDialog.getSaveFileName


if QT_API in [QT_API_PYQT6, QT_API_PYQT5, QT_API_PYSIDE6, QT_API_PYSIDE2]:
    _setup_pyqt5plus()
elif QT_API is None:  # See above re: dict.__getitem__.
    _candidates = [
        (_setup_pyqt5plus, QT_API_PYQT6),
        (_setup_pyqt5plus, QT_API_PYSIDE6),
        (_setup_pyqt5plus, QT_API_PYQT5),
        (_setup_pyqt5plus, QT_API_PYSIDE2),
    ]
    for _setup, QT_API in _candidates:
        try:
            _setup()
        except ImportError:
            continue
        break
    else:
        raise ImportError("Failed to import any qt binding")
else:  # We should not get there.
    raise AssertionError(f"Unexpected QT_API: {QT_API}")


# Fixes issues with Big Sur
# https://bugreports.qt.io/browse/QTBUG-87014, fixed in qt 5.15.2
if (sys.platform == 'darwin' and
        parse_version(platform.mac_ver()[0]) >= parse_version("10.16") and
        parse_version(QtCore.qVersion()) < parse_version("5.15.2") and
        "QT_MAC_WANTS_LAYER" not in os.environ):
    os.environ["QT_MAC_WANTS_LAYER"] = "1"


# These globals are only defined for backcompatibility purposes.
ETS = dict(pyqt5=(QT_API_PYQT5, 5), pyside2=(QT_API_PYSIDE2, 5))

QT_RC_MAJOR_VERSION = int(QtCore.qVersion().split(".")[0])


# PyQt6 enum compat helpers.


_to_int = operator.attrgetter("value") if QT_API == "PyQt6" else int


@functools.lru_cache(None)
def _enum(name):
    # foo.bar.Enum.Entry (PyQt6) <=> foo.bar.Entry (non-PyQt6).
    return operator.attrgetter(
        name if QT_API == 'PyQt6' else name.rpartition(".")[0]
    )(sys.modules[QtCore.__package__])


# Backports.


def _exec(obj):
    # exec on PyQt6, exec_ elsewhere.
    obj.exec() if hasattr(obj, "exec") else obj.exec_()


def _devicePixelRatioF(obj):
    """
    Return obj.devicePixelRatioF() with graceful fallback for older Qt.

    This can be replaced by the direct call when we require Qt>=5.6.
    """
    try:
        # Not available on Qt<5.6
        return obj.devicePixelRatioF() or 1
    except AttributeError:
        pass
    try:
        # Not available on Qt4 or some older Qt5.
        # self.devicePixelRatio() returns 0 in rare cases
        return obj.devicePixelRatio() or 1
    except AttributeError:
        return 1


def _setDevicePixelRatio(obj, val):
    """
    Call obj.setDevicePixelRatio(val) with graceful fallback for older Qt.

    This can be replaced by the direct call when we require Qt>=5.6.
    """
    if hasattr(obj, 'setDevicePixelRatio'):
        # Not available on Qt4 or some older Qt5.
        obj.setDevicePixelRatio(val)

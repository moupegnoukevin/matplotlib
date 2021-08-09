import copy
import importlib
import inspect
import os
import signal
import subprocess
import sys

from datetime import date, datetime
from unittest import mock

import pytest

import matplotlib
from matplotlib import pyplot as plt
from matplotlib._pylab_helpers import Gcf
from matplotlib import _c_internal_utils


try:
    from matplotlib.backends.qt_compat import QtGui, QtWidgets
    from matplotlib.backends.qt_editor import _formlayout
except ImportError:
    pytestmark = pytest.mark.skip('No usable Qt bindings')


@pytest.fixture
def qt_core(request):
    backend, = request.node.get_closest_marker('backend').args
    qt_compat = pytest.importorskip('matplotlib.backends.qt_compat')
    QtCore = qt_compat.QtCore

    return QtCore


@pytest.mark.backend('QtAgg', skip_on_importerror=True)
def test_fig_close():
    # save the state of Gcf.figs
    init_figs = copy.copy(Gcf.figs)

    # make a figure using pyplot interface
    fig = plt.figure()

    # simulate user clicking the close button by reaching in
    # and calling close on the underlying Qt object
    fig.canvas.manager.window.close()

    # assert that we have removed the reference to the FigureManager
    # that got added by plt.figure()
    assert init_figs == Gcf.figs


@pytest.mark.backend('QtAgg', skip_on_importerror=True)
def test_fig_signals(qt_core):
    # Create a figure
    plt.figure()

    # Access signals
    event_loop_signal = None

    # Callback to fire during event loop: save SIGINT handler, then exit
    def fire_signal_and_quit():
        # Save event loop signal
        nonlocal event_loop_signal
        event_loop_signal = signal.getsignal(signal.SIGINT)

        # Request event loop exit
        qt_core.QCoreApplication.exit()

    # Timer to exit event loop
    qt_core.QTimer.singleShot(0, fire_signal_and_quit)

    # Save original SIGINT handler
    original_signal = signal.getsignal(signal.SIGINT)

    # Use our own SIGINT handler to be 100% sure this is working
    def CustomHandler(signum, frame):
        pass

    signal.signal(signal.SIGINT, CustomHandler)

    # mainloop() sets SIGINT, starts Qt event loop (which triggers timer and
    # exits) and then mainloop() resets SIGINT
    matplotlib.backends.backend_qt._BackendQT.mainloop()

    # Assert: signal handler during loop execution is signal.SIG_DFL
    assert event_loop_signal == signal.SIG_DFL

    # Assert: current signal handler is the same as the one we set before
    assert CustomHandler == signal.getsignal(signal.SIGINT)

    # Reset SIGINT handler to what it was before the test
    signal.signal(signal.SIGINT, original_signal)


@pytest.mark.parametrize(
    'qt_key, qt_mods, answer',
    [
        ('Key_A', ['ShiftModifier'], 'A'),
        ('Key_A', [], 'a'),
        ('Key_A', ['ControlModifier'], 'ctrl+a'),
        ('Key_Aacute', ['ShiftModifier'],
         '\N{LATIN CAPITAL LETTER A WITH ACUTE}'),
        ('Key_Aacute', [],
         '\N{LATIN SMALL LETTER A WITH ACUTE}'),
        ('Key_Control', ['AltModifier'], 'alt+control'),
        ('Key_Alt', ['ControlModifier'], 'ctrl+alt'),
        ('Key_Aacute', ['ControlModifier', 'AltModifier', 'MetaModifier'],
         'ctrl+alt+super+\N{LATIN SMALL LETTER A WITH ACUTE}'),
        ('Key_Play', [], None),
        ('Key_Backspace', [], 'backspace'),
        ('Key_Backspace', ['ControlModifier'], 'ctrl+backspace'),
    ],
    ids=[
        'shift',
        'lower',
        'control',
        'unicode_upper',
        'unicode_lower',
        'alt_control',
        'control_alt',
        'modifier_order',
        'non_unicode_key',
        'backspace',
        'backspace_mod',
    ]
)
@pytest.mark.parametrize('backend', [
    # Note: the value is irrelevant; the important part is the marker.
    pytest.param(
        'Qt5Agg',
        marks=pytest.mark.backend('Qt5Agg', skip_on_importerror=True)),
    pytest.param(
        'QtAgg',
        marks=pytest.mark.backend('QtAgg', skip_on_importerror=True)),
])
def test_correct_key(backend, qt_core, qt_key, qt_mods, answer):
    """
    Make a figure.
    Send a key_press_event event (using non-public, qtX backend specific api).
    Catch the event.
    Assert sent and caught keys are the same.
    """
    from matplotlib.backends.qt_compat import _enum, _to_int
    qt_mod = _enum("QtCore.Qt.KeyboardModifier").NoModifier
    for mod in qt_mods:
        qt_mod |= getattr(_enum("QtCore.Qt.KeyboardModifier"), mod)

    class _Event:
        def isAutoRepeat(self): return False
        def key(self): return _to_int(getattr(_enum("QtCore.Qt.Key"), qt_key))
        def modifiers(self): return qt_mod

    def on_key_press(event):
        assert event.key == answer

    qt_canvas = plt.figure().canvas
    qt_canvas.mpl_connect('key_press_event', on_key_press)
    qt_canvas.keyPressEvent(_Event())


@pytest.mark.backend('QtAgg', skip_on_importerror=True)
def test_device_pixel_ratio_change():
    """
    Make sure that if the pixel ratio changes, the figure dpi changes but the
    widget remains the same logical size.
    """

    prop = 'matplotlib.backends.backend_qt.FigureCanvasQT.devicePixelRatioF'
    with mock.patch(prop) as p:
        p.return_value = 3

        fig = plt.figure(figsize=(5, 2), dpi=120)
        qt_canvas = fig.canvas
        qt_canvas.show()

        def set_device_pixel_ratio(ratio):
            p.return_value = ratio

            # The value here doesn't matter, as we can't mock the C++ QScreen
            # object, but can override the functional wrapper around it.
            # Emitting this event is simply to trigger the DPI change handler
            # in Matplotlib in the same manner that it would occur normally.
            screen.logicalDotsPerInchChanged.emit(96)

            qt_canvas.draw()
            qt_canvas.flush_events()

            # Make sure the mocking worked
            assert qt_canvas.device_pixel_ratio == ratio

        qt_canvas.manager.show()
        size = qt_canvas.size()
        screen = qt_canvas.window().windowHandle().screen()
        set_device_pixel_ratio(3)

        # The DPI and the renderer width/height change
        assert fig.dpi == 360
        assert qt_canvas.renderer.width == 1800
        assert qt_canvas.renderer.height == 720

        # The actual widget size and figure logical size don't change.
        assert size.width() == 600
        assert size.height() == 240
        assert qt_canvas.get_width_height() == (600, 240)
        assert (fig.get_size_inches() == (5, 2)).all()

        set_device_pixel_ratio(2)

        # The DPI and the renderer width/height change
        assert fig.dpi == 240
        assert qt_canvas.renderer.width == 1200
        assert qt_canvas.renderer.height == 480

        # The actual widget size and figure logical size don't change.
        assert size.width() == 600
        assert size.height() == 240
        assert qt_canvas.get_width_height() == (600, 240)
        assert (fig.get_size_inches() == (5, 2)).all()

        set_device_pixel_ratio(1.5)

        # The DPI and the renderer width/height change
        assert fig.dpi == 180
        assert qt_canvas.renderer.width == 900
        assert qt_canvas.renderer.height == 360

        # The actual widget size and figure logical size don't change.
        assert size.width() == 600
        assert size.height() == 240
        assert qt_canvas.get_width_height() == (600, 240)
        assert (fig.get_size_inches() == (5, 2)).all()


@pytest.mark.backend('QtAgg', skip_on_importerror=True)
def test_subplottool():
    fig, ax = plt.subplots()
    with mock.patch("matplotlib.backends.qt_compat._exec", lambda obj: None):
        fig.canvas.manager.toolbar.configure_subplots()


@pytest.mark.backend('QtAgg', skip_on_importerror=True)
def test_figureoptions():
    fig, ax = plt.subplots()
    ax.plot([1, 2])
    ax.imshow([[1]])
    ax.scatter(range(3), range(3), c=range(3))
    with mock.patch("matplotlib.backends.qt_compat._exec", lambda obj: None):
        fig.canvas.manager.toolbar.edit_parameters()


@pytest.mark.backend('QtAgg', skip_on_importerror=True)
def test_figureoptions_with_datetime_axes():
    fig, ax = plt.subplots()
    xydata = [
        datetime(year=2021, month=1, day=1),
        datetime(year=2021, month=2, day=1)
    ]
    ax.plot(xydata, xydata)
    with mock.patch("matplotlib.backends.qt_compat._exec", lambda obj: None):
        fig.canvas.manager.toolbar.edit_parameters()


@pytest.mark.backend('QtAgg', skip_on_importerror=True)
def test_double_resize():
    # Check that resizing a figure twice keeps the same window size
    fig, ax = plt.subplots()
    fig.canvas.draw()
    window = fig.canvas.manager.window

    w, h = 3, 2
    fig.set_size_inches(w, h)
    assert fig.canvas.width() == w * matplotlib.rcParams['figure.dpi']
    assert fig.canvas.height() == h * matplotlib.rcParams['figure.dpi']

    old_width = window.width()
    old_height = window.height()

    fig.set_size_inches(w, h)
    assert window.width() == old_width
    assert window.height() == old_height


@pytest.mark.backend('QtAgg', skip_on_importerror=True)
def test_canvas_reinit():
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

    called = False

    def crashing_callback(fig, stale):
        nonlocal called
        fig.canvas.draw_idle()
        called = True

    fig, ax = plt.subplots()
    fig.stale_callback = crashing_callback
    # this should not raise
    canvas = FigureCanvasQTAgg(fig)
    fig.stale = True
    assert called


@pytest.mark.backend('Qt5Agg', skip_on_importerror=True)
def test_form_widget_get_with_datetime_and_date_fields():
    if not QtWidgets.QApplication.instance():
        QtWidgets.QApplication()
    form = [
        ("Datetime field", datetime(year=2021, month=3, day=11)),
        ("Date field", date(year=2021, month=3, day=11))
    ]
    widget = _formlayout.FormWidget(form)
    widget.setup()
    values = widget.get()
    assert values == [
        datetime(year=2021, month=3, day=11),
        date(year=2021, month=3, day=11)
    ]


# The source of this function gets extracted and run in another process, so it
# must be fully self-contained.
def _test_enums_impl():
    import sys

    from matplotlib.backends.qt_compat import _enum, _to_int, QtCore
    from matplotlib.backend_bases import cursors, MouseButton

    _enum("QtGui.QDoubleValidator.State").Acceptable

    _enum("QtWidgets.QDialogButtonBox.StandardButton").Ok
    _enum("QtWidgets.QDialogButtonBox.StandardButton").Cancel
    _enum("QtWidgets.QDialogButtonBox.StandardButton").Apply
    for btn_type in ["Ok", "Cancel"]:
        getattr(_enum("QtWidgets.QDialogButtonBox.StandardButton"), btn_type)

    _enum("QtGui.QImage.Format").Format_ARGB32_Premultiplied
    _enum("QtGui.QImage.Format").Format_ARGB32_Premultiplied
    # SPECIAL_KEYS are Qt::Key that do *not* return their unicode name instead
    # they have manually specified names.
    SPECIAL_KEYS = {
        _to_int(getattr(_enum("QtCore.Qt.Key"), k)): v
        for k, v in [
            ("Key_Escape", "escape"),
            ("Key_Tab", "tab"),
            ("Key_Backspace", "backspace"),
            ("Key_Return", "enter"),
            ("Key_Enter", "enter"),
            ("Key_Insert", "insert"),
            ("Key_Delete", "delete"),
            ("Key_Pause", "pause"),
            ("Key_SysReq", "sysreq"),
            ("Key_Clear", "clear"),
            ("Key_Home", "home"),
            ("Key_End", "end"),
            ("Key_Left", "left"),
            ("Key_Up", "up"),
            ("Key_Right", "right"),
            ("Key_Down", "down"),
            ("Key_PageUp", "pageup"),
            ("Key_PageDown", "pagedown"),
            ("Key_Shift", "shift"),
            # In OSX, the control and super (aka cmd/apple) keys are switched.
            ("Key_Control", "control" if sys.platform != "darwin" else "cmd"),
            ("Key_Meta", "meta" if sys.platform != "darwin" else "control"),
            ("Key_Alt", "alt"),
            ("Key_CapsLock", "caps_lock"),
            ("Key_F1", "f1"),
            ("Key_F2", "f2"),
            ("Key_F3", "f3"),
            ("Key_F4", "f4"),
            ("Key_F5", "f5"),
            ("Key_F6", "f6"),
            ("Key_F7", "f7"),
            ("Key_F8", "f8"),
            ("Key_F9", "f9"),
            ("Key_F10", "f10"),
            ("Key_F10", "f11"),
            ("Key_F12", "f12"),
            ("Key_Super_L", "super"),
            ("Key_Super_R", "super"),
        ]
    }
    # Define which modifier keys are collected on keyboard events.  Elements
    # are (Qt::KeyboardModifiers, Qt::Key) tuples.  Order determines the
    # modifier order (ctrl+alt+...) reported by Matplotlib.
    _MODIFIER_KEYS = [
        (
            _to_int(getattr(_enum("QtCore.Qt.KeyboardModifier"), mod)),
            _to_int(getattr(_enum("QtCore.Qt.Key"), key)),
        )
        for mod, key in [
            ("ControlModifier", "Key_Control"),
            ("AltModifier", "Key_Alt"),
            ("ShiftModifier", "Key_Shift"),
            ("MetaModifier", "Key_Meta"),
        ]
    ]
    cursord = {
        k: getattr(_enum("QtCore.Qt.CursorShape"), v)
        for k, v in [
            (cursors.MOVE, "SizeAllCursor"),
            (cursors.HAND, "PointingHandCursor"),
            (cursors.POINTER, "ArrowCursor"),
            (cursors.SELECT_REGION, "CrossCursor"),
            (cursors.WAIT, "WaitCursor"),
        ]
    }

    buttond = {
        getattr(_enum("QtCore.Qt.MouseButton"), k): v
        for k, v in [
            ("LeftButton", MouseButton.LEFT),
            ("RightButton", MouseButton.RIGHT),
            ("MiddleButton", MouseButton.MIDDLE),
            ("XButton1", MouseButton.BACK),
            ("XButton2", MouseButton.FORWARD),
        ]
    }

    _enum("QtCore.Qt.WidgetAttribute").WA_OpaquePaintEvent
    _enum("QtCore.Qt.FocusPolicy").StrongFocus
    _enum("QtCore.Qt.ToolBarArea").TopToolBarArea
    _enum("QtCore.Qt.ToolBarArea").TopToolBarArea
    _enum("QtCore.Qt.AlignmentFlag").AlignRight
    _enum("QtCore.Qt.AlignmentFlag").AlignVCenter
    _enum("QtWidgets.QSizePolicy.Policy").Expanding
    _enum("QtWidgets.QSizePolicy.Policy").Ignored
    _enum("QtCore.Qt.MaskMode").MaskOutColor
    _enum("QtCore.Qt.ToolBarArea").TopToolBarArea
    _enum("QtCore.Qt.ToolBarArea").TopToolBarArea
    _enum("QtCore.Qt.AlignmentFlag").AlignRight
    _enum("QtCore.Qt.AlignmentFlag").AlignVCenter
    _enum("QtWidgets.QSizePolicy.Policy").Expanding
    _enum("QtWidgets.QSizePolicy.Policy").Ignored


def _get_testable_qt_backends():
    envs = []
    for deps, env in [
            ([qt_api], {"MPLBACKEND": "qtagg", "QT_API": qt_api})
            for qt_api in ["PyQt6", "PySide6", "PyQt5", "PySide2"]
    ]:
        reason = None
        missing = [dep for dep in deps if not importlib.util.find_spec(dep)]
        if (sys.platform == "linux" and
                not _c_internal_utils.display_is_valid()):
            reason = "$DISPLAY and $WAYLAND_DISPLAY are unset"
        elif missing:
            reason = "{} cannot be imported".format(", ".join(missing))
        elif env["MPLBACKEND"] == 'macosx' and os.environ.get('TF_BUILD'):
            reason = "macosx backend fails on Azure"
        marks = []
        if reason:
            marks.append(pytest.mark.skip(
                reason=f"Skipping {env} because {reason}"))
        envs.append(pytest.param(env, marks=marks, id=str(env)))
    return envs

_test_timeout = 10  # Empirically, 1s is not enough on CI.


@pytest.mark.parametrize("env", _get_testable_qt_backends())
def test_enums_available(env):
    proc = subprocess.run(
        [sys.executable, "-c",
         inspect.getsource(_test_enums_impl) + "\n_test_enums_impl()"],
        env={**os.environ, "SOURCE_DATE_EPOCH": "0", **env},
        timeout=_test_timeout, check=True,
        stdout=subprocess.PIPE, universal_newlines=True)

#-----------------------------------------------------------------------------
# Title      : PyRogue PyDM Live Channel Histogram Widget
#-----------------------------------------------------------------------------
# Displays a live PHA histogram for a selected node/board/rena/channel along
# with per channel event counts for the selected rena. Data is accumulated
# in the C++ RenaDataDecoder and read out through the HistogramView device.
#-----------------------------------------------------------------------------

import numpy as np
import pyqtgraph as pg

from pydm.widgets.frame import PyDMFrame
from pydm.widgets import PyDMSpinbox, PyDMPushButton
from pyrogue.pydm.data_plugins.rogue_plugin import nodeFromAddress
from qtpy.QtCore import Qt, QTimer
from qtpy.QtWidgets import (QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
                            QGroupBox, QLabel, QCheckBox)


class HistogramWindow(PyDMFrame):
    def __init__(self, parent=None, init_channel=None):
        PyDMFrame.__init__(self, parent, init_channel)
        self._node = None

    def connection_changed(self, connected):
        build = (self._node is None) and (self._connected != connected and connected is True)
        super(HistogramWindow, self).connection_changed(connected)

        if not build:
            return

        self._node = nodeFromAddress(self.channel)
        self._path = self.channel

        vb = QVBoxLayout()
        self.setLayout(vb)

        hb = QHBoxLayout()
        vb.addLayout(hb)

        gb = QGroupBox('Channel Select')
        hb.addWidget(gb)

        fl = QFormLayout()
        fl.setRowWrapPolicy(QFormLayout.DontWrapRows)
        fl.setFormAlignment(Qt.AlignHCenter | Qt.AlignTop)
        fl.setLabelAlignment(Qt.AlignRight)
        gb.setLayout(fl)

        for name, label in [('NodeSelect',    'Node Select:'),
                            ('BoardSelect',   'Board Select:'),
                            ('RenaSelect',    'Rena Select:'),
                            ('ChannelSelect', 'Channel Select:')]:
            w = PyDMSpinbox(parent=None, init_channel=self._path + '.' + name)
            w.precision             = 0
            w.showUnits             = False
            w.precisionFromPV       = False
            w.alarmSensitiveContent = False
            w.alarmSensitiveBorder  = True
            w.showStepExponent      = False
            w.writeOnPress          = True
            fl.addRow(label, w)

        gb = QGroupBox('Control / Stats')
        hb.addWidget(gb)

        fl = QFormLayout()
        fl.setRowWrapPolicy(QFormLayout.DontWrapRows)
        fl.setFormAlignment(Qt.AlignHCenter | Qt.AlignTop)
        fl.setLabelAlignment(Qt.AlignRight)
        gb.setLayout(fl)

        w = PyDMPushButton(label='Reset',
                           pressValue=1,
                           init_channel=self._path + '.ResetHistogram/disp')
        fl.addRow('Reset Histogram:', w)

        self._logScale = QCheckBox()
        self._logScale.stateChanged.connect(self._logScaleChanged)
        fl.addRow('Log Scale:', self._logScale)

        self._entriesLabel = QLabel('0')
        fl.addRow('Entries:', self._entriesLabel)

        self._meanLabel = QLabel('0.00')
        fl.addRow('Mean:', self._meanLabel)

        self._sigmaLabel = QLabel('0.00')
        fl.addRow('Sigma:', self._sigmaLabel)

        self._plot = pg.PlotWidget()
        self._plot.setLabel('bottom', 'PHA ADC Value')
        self._plot.setLabel('left', 'Counts')
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._curve = self._plot.plot(pen=pg.mkPen(width=1))
        vb.addWidget(self._plot, stretch=1)

        gb = QGroupBox('Rena Channel Counts')
        vb.addWidget(gb)

        gl = QGridLayout()
        gb.setLayout(gl)

        self._countLabels = []
        for ch in range(36):
            lbl = QLabel(f'{ch}: 0')
            lbl.setAlignment(Qt.AlignCenter)
            self._countLabels.append(lbl)
            gl.addWidget(lbl, ch // 6, ch % 6)

        self._xData = np.arange(4096)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)

    def _logScaleChanged(self, state):
        self._plot.getPlotItem().setLogMode(x=False, y=(state != 0))

    def _refresh(self):
        try:
            hist    = np.array(self._node.Histogram.get(), dtype=np.float64)
            counts  = self._node.ChanCounts.get()
            selChan = self._node.ChannelSelect.value()
        except Exception:
            return

        # Update statistics
        entries = hist.sum()
        if entries > 0:
            mean  = np.sum(self._xData * hist) / entries
            sigma = np.sqrt(np.sum(((self._xData - mean) ** 2) * hist) / entries)
        else:
            mean  = 0.0
            sigma = 0.0

        self._entriesLabel.setText(f'{int(entries)}')
        self._meanLabel.setText(f'{mean:.2f}')
        self._sigmaLabel.setText(f'{sigma:.2f}')

        # Avoid log(0) artifacts when in log mode
        if self._logScale.isChecked():
            hist = np.maximum(hist, 0.1)

        self._curve.setData(self._xData, hist)

        # Update per channel counts, highlight the selected channel
        for ch in range(36):
            self._countLabels[ch].setText(f'{ch}: {counts[ch]}')
            if ch == selChan:
                self._countLabels[ch].setStyleSheet('font-weight: bold; color: orange;')
            else:
                self._countLabels[ch].setStyleSheet('')

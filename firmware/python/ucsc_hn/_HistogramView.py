import pyrogue as pr

class HistogramView(pr.Device):
    def __init__(self, nodeCount, **kwargs):
        super().__init__(description="Live Channel Histogram Monitor", **kwargs)

        self._nodeCount = nodeCount
        self._applied = False

        ##############################
        # Select
        ##############################

        self.add(pr.LocalVariable(name='NodeSelect',
                                 value=1,
                                 mode='RW',
                                 minimum=1,
                                 maximum=self._nodeCount,
                                 localSet=self._selectSet,
                                 description="Node Selection"))

        self.add(pr.LocalVariable(name='BoardSelect',
                                 value=1,
                                 mode='RW',
                                 minimum=1,
                                 maximum=30,
                                 localSet=self._selectSet,
                                 description="Board Selection"))

        self.add(pr.LocalVariable(name='RenaSelect',
                                 value=0,
                                 mode='RW',
                                 minimum=0,
                                 maximum=1,
                                 localSet=self._selectSet,
                                 description="Rena Selection"))

        self.add(pr.LocalVariable(name='ChannelSelect',
                                 value=0,
                                 mode='RW',
                                 minimum=0,
                                 maximum=35,
                                 localSet=self._selectSet,
                                 description="Channel Selection"))

        ##############################
        # Data
        ##############################

        self.add(pr.LocalVariable(name='Histogram',
                                 value=[0]*4096,
                                 mode='RO',
                                 hidden=True,
                                 localGet=self._getHistogram,
                                 description="PHA histogram of the selected channel, 4096 bins"))

        self.add(pr.LocalVariable(name='ChanCounts',
                                 value=[0]*36,
                                 mode='RO',
                                 hidden=True,
                                 localGet=self._getChanCounts,
                                 description="Event counts for the 36 channels of the selected rena"))

        self.add(pr.Command(name='ResetHistogram',
                            function=self._reset,
                            description="Clear the histogram and channel counts for the selected node"))

    def _decoder(self, node):
        return self.root.Node[node].RenaArray.DataDecoder._processor

    def _updateTarget(self):
        node    = self.NodeSelect.value()
        board   = self.BoardSelect.value()
        rena    = self.RenaSelect.value()
        channel = self.ChannelSelect.value()

        for n in range(1, self._nodeCount+1):
            if n == node:
                self._decoder(n).setHistChannel(board, rena, channel)
                self._decoder(n).setHistEnable(1)
            else:
                self._decoder(n).setHistEnable(0)

        self._applied = True

    def _selectSet(self, value):
        if self.root is not None:
            try:
                self._updateTarget()
            except Exception as e:
                pr.logException(self._log, e)

    def _getHistogram(self):
        if not self._applied:
            self._updateTarget()

        node = self.NodeSelect.value()
        return self._decoder(node).getHistogram()

    def _getChanCounts(self):
        node  = self.NodeSelect.value()
        board = self.BoardSelect.value()
        rena  = self.RenaSelect.value()
        return self._decoder(node).getChanCountList(board, rena)

    def _reset(self):
        node = self.NodeSelect.value()
        self._decoder(node).resetHistogram()
        self._decoder(node).resetChanCounts()

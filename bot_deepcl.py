from __future__ import print_function

import tempfile
import subprocess
import os
import logging
import array
import numpy as np
import time

from players import DistributionBot, DistWrappingMaxPlayer
import gomill

import cubes

class DeepCL_IO(object):
    def __init__(self,
                 deepclexec_path,
                 options={
                     "dataset" : "kgsgo", # needed for normalization
                     # "weightsFile": "weights.dat", # default value
                     # see 'deepclexec -h' for other options
                     # CAVEEAT: normalization has to be set up the same
                     # as when the CNN was trained
                     }):
        # DeepCL works with 4 byte floats, so we need to ensure we have
        # the same size, if this fails, we could probably reimplement it
        # using struct module
        self.itemsize = 4
        a = array.array('f')
        assert a.itemsize == self.itemsize

        self.deepclexec_path = deepclexec_path

        for res_opt in ['inputfile', 'outputfile']:
            if res_opt in options:
                logging.warn("DeepCL_IO: '%s' option is reserved, overriding."%res_opt)

        # first create the named pipes for IO
        self.tempdir = tempfile.mkdtemp()

        self.pipe_fn_to = os.path.join(self.tempdir, "PIPE_to")
        self.pipe_fn_from = os.path.join(self.tempdir, "PIPE_from")

        options['inputfile'] = self.pipe_fn_to
        options['outputfile'] = self.pipe_fn_from

        os.mkfifo(self.pipe_fn_to)
        os.mkfifo(self.pipe_fn_from)

        self.p = subprocess.Popen([deepclexec_path] + [ "%s=%s"%(k, v) for k, v in options.iteritems() ],
                                  stdin=None,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT)

        time.sleep(3)
        # if the process is dead already,
        # we cannot proceed, we would hang on the first pipe (below)
        if self.p.poll() != None:
            logging.debug("deepclexec died unexpectedly")
            self.gather_sub_logs()
            raise RuntimeError("deepclexec died unexpectedly")

        # this might seem like a too verbose piece of code, but
        # unfortunately, open() hangs if the other side is not opened,
        # so it is good to see this in log in the case...
        logging.debug("Setting up pipe: "+ self.pipe_fn_to)
        logging.debug("(If this hangs, deepclexec failed to start properly)")
        self.pipe_to = open(self.pipe_fn_to, 'wb')
        logging.debug("Setting up pipe: "+ self.pipe_fn_from)
        self.pipe_from = open(self.pipe_fn_from, 'rb')
        logging.debug("Pipes set up.")

    def gather_sub_logs(self):
        logging.debug("Gathering subprocess logs.")
        stdout, stderr =  self.p.communicate()
        logging.debug("stdout:\n"+str(stdout) +"\n")
        logging.debug("stderr:\n"+str(stderr) +"\n")

    def close_pipes(self):
        self.pipe_to.close()
        self.pipe_from.close()

    def close(self):
        self.close_pipes()
        self.gather_sub_logs()
        #self.p.terminate()

        os.unlink(self.pipe_fn_to)
        os.unlink(self.pipe_fn_from)
        os.rmdir(self.tempdir)

    def write_cube(self, cube_array):
        cube_array.tofile(self.pipe_to)
        self.pipe_to.flush()

    def read_response(self, side):
        return np.fromfile(self.pipe_from, dtype="float32", count=side*side)

class DeepCLDistBot(DistributionBot):
    def __init__(self, deepcl_io):
        super(DeepCLDistBot,  self).__init__()
        self.deepcl_io = deepcl_io

    def gen_probdist_raw(self, state, player):
        cube = cubes.get_cube_deepcl(state.board, state.ko_point, player)

        try:
            logging.debug("Sending data, cube.shape = %s, %d B"%(cube.shape,
                                                                 self.deepcl_io.itemsize * reduce(lambda a, b:a*b, cube.shape)))
            self.deepcl_io.write_cube(cube)
            #logging.debug("\n%s"%str(cube))

            logging.debug("Reading response from CNN...")
            response = self.deepcl_io.read_response(state.board.side)
        except:
            self.deepcl_io.close_pipes()
            self.deepcl_io.gather_sub_logs()
            raise

        logging.debug("Got response of size %d B"%(self.deepcl_io.itemsize * len(response)))
        #logging.debug("\n%s"%(str(response)))

        return response.reshape((state.board.side, state.board.side))

    def close(self):
        self.deepcl_io.close()


if __name__ == "__main__":
    def test_bot():
        logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s',
                            level=logging.DEBUG)

        DCL_PATH = '/home/jm/prj/DeepCL/'
        deepcl_io = DeepCL_IO(os.path.join(DCL_PATH, 'build/deepclexec'), options={
            #'dataset':'kgsgo',
            'weightsfile': DCL_PATH + "weights.dat",
            'datadir': os.path.join(DCL_PATH, 'data/kgsgo'),
            # needed to establish normalization parameters
            'trainfile': 'kgsgo-train10k-v2.dat',})

        player = DistWrappingMaxPlayer(DeepCLDistBot(deepcl_io))

        class State:
            pass
        s = State()

        b = gomill.boards.Board(19)
        s.board = b
        s.ko_point = None
        logging.debug("bot: %s"% repr(player.genmove(s, 'w').move))

        #player.handle_quit([])

    test_bot()
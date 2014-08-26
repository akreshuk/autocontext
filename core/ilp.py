import os
import vigra
import numpy


# The ILP class can be used for basic interactions with ilp files.
class ILP:

    @staticmethod
    def filepath(lane_number):
        lane_number = str(lane_number).zfill(4)
        return "Input Data/infos/lane" + lane_number + "/Raw Data/filePath"

    @staticmethod
    def axisorder(lane_number):
        lane_number = str(lane_number).zfill(4)
        return "Input Data/infos/lane" + lane_number + "/Raw Data/axisorder"

    @staticmethod
    def axistags(lane_number):
        lane_number = str(lane_number).zfill(4)
        return "Input Data/infos/lane" + lane_number + "/Raw Data/axistags"

    @staticmethod
    def labelpath(lane_number, block_number):
        lane_number = str(lane_number).zfill(3)
        block_number = str(block_number).zfill(4)
        return "PixelClassification/LabelSets/labels" + lane_number + "/block" + block_number

    @staticmethod
    def xyzc_axistags():
        return """{
"axes": [
  {
    "key": "x",
    "typeFlags": 2,
    "resolution": 0,
    "description": ""
  },
  {
    "key": "y",
    "typeFlags": 2,
    "resolution": 0,
    "description": ""
  },
  {
    "key": "z",
    "typeFlags": 2,
    "resolution": 0,
    "description": ""
  },
  {
    "key": "c",
    "typeFlags": 1,
    "resolution": 0,
    "description": ""
  }
]
}"""

    export_key = "exported_data"

    def __init__(self, ilastik_cmd, project_name, lane_number=0):
        self.ilastik_cmd = ilastik_cmd
        self._project_name = project_name
        self._lane_number = lane_number

        # Read data from project file.
        raw_path = vigra.readHDF5(project_name, ILP.filepath(lane_number))
        raw_key = os.path.basename(raw_path)
        project_dir = os.path.dirname(os.path.realpath(project_name))
        raw_path = os.path.join(project_dir, raw_path[:-len(raw_key)-1])
        self._raw_path = raw_path
        self._raw_key = raw_key
        self._raw_axisorder = vigra.readHDF5(project_name, ILP.axisorder(lane_number))

        # Get the number of label blocks.
        s_lane_number = str(lane_number).zfill(3)
        from h5py import File
        proj = File(project_name, "r")
        block_count = len(proj['PixelClassification']['LabelSets']['labels' + s_lane_number].keys())
        proj.close()
        self._number_label_blocks = block_count

        # Read number of channels from raw data.
        self._number_channels = 1
        self._number_probability_channels = 0
        if self._raw_axisorder != "xyz":
            raw = vigra.readHDF5(raw_path, raw_key)
            self._number_of_channels = raw.shape[-1]

    # Getter for project name.
    @property
    def project_name(self):
        return self._project_name

    # Getter for lane number.
    @property
    def lane_number(self):
        return self._lane_number

    # Getter for raw path.
    @property
    def raw_path(self):
        return self._raw_path

    # Getter for raw key.
    @property
    def raw_key(self):
        return self._raw_key

    # Getter for raw axisorder.
    @property
    def raw_axisorder(self):
        return self._raw_axisorder

    # Getter for number label blocks.
    @property
    def number_label_blocks(self):
        return self._number_label_blocks

    # Getter for number channels.
    @property
    def number_channels(self):
        return self._number_channels

    # Getter for number probability channels.
    @property
    def number_probability_channels(self):
        return self._number_probability_channels

    # The string raw_path/raw_key is used in ilp files as path to the raw data.
    @property
    def raw_path_key(self):
        return self._raw_path + "/" + self._raw_key

    # Copy the raw data and reshape it to a multichannel dataset.
    def copy_raw_data_multichannel(self, file_suffix="_copy"):
        raw = vigra.readHDF5(self.raw_path, self.raw_key)

        # Reshape raw data if necessary.
        if self.raw_axisorder == "xyz":
            raw = numpy.reshape(raw, raw.shape+(1,))

            # Update the project file.
            vigra.writeHDF5("xyzc", self.project_name, ILP.axisorder(self.lane_number))
            vigra.writeHDF5(ILP.xyzc_axistags(), self.project_name, ILP.axistags(self.lane_number))

        # Copy the data.
        self._raw_path = self.raw_path[:-3] + file_suffix + ".h5"
        if os.path.isfile(self.raw_path):
            os.remove(self.raw_path)
        vigra.writeHDF5(raw, self.raw_path, self.raw_key, compression="lzf")

        # Update the project file.
        vigra.writeHDF5(self.raw_path_key, self.project_name, ILP.filepath(self.lane_number))

    # Retrain the project using ilastik.
    def run_ilastik(self, probs_filename, delete_batch=False):
        # Run ilastik.
        if os.path.isfile(probs_filename):
            os.remove(probs_filename)
        cmd = '{} --headless --project {} --output_format hdf5 --output_filename_format {} {} --retrain'\
            .format(self.ilastik_cmd, self.project_name, probs_filename, self.raw_path_key)
        print cmd
        os.system(cmd)

        # Remove batch entries from project file.
        if delete_batch:
            from h5py import File
            proj = File(self.project_name, "r+")
            del proj['Batch Inputs']
            del proj['Batch Prediction Output Locations']
            proj.close()

            #TODO
            # Remove the created memory holes in the h5 file
            # (see "Deleting a dataset doesn't always reduce the file size" on
            # https://github.com/h5py/h5py/wiki/Common-Problems).
            # os.system("h5repack -i projectfile.h5 -o tempfile.h5")
            # os.remove("projectfile.h5")
            # os.rename("tempfile.h5", "projectfile.h5")

    # Merge probabilities into the raw data.
    def merge_probs_into_raw(self, probs_filename):
        # Read raw and probability data.
        raw = vigra.readHDF5(self.raw_path, self.raw_key)
        probs = vigra.readHDF5(probs_filename, ILP.export_key)
        self._number_probability_channels = probs.shape[-1]

        # Merge raw and probabilitiy data into one array.
        raw_probs_shape = list(raw.shape)
        raw_probs_shape[-1] = self.number_channels + self.number_probability_channels
        raw_probs_shape = tuple(raw_probs_shape)
        raw_probs = numpy.zeros(raw_probs_shape)
        raw_probs[:, :, :, :self.number_channels] = raw[:, :, :, :self.number_channels]
        raw_probs[:, :, :, self.number_channels:] = probs

        # Save the result.
        vigra.writeHDF5(raw_probs, self.raw_path, self.raw_key, compression="lzf")
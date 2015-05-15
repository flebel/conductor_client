import os
from PySide import QtGui, QtCore
import nuke
from conductor.tools import file_utils, nuke_utils, pyside_utils
from conductor import submitter


'''
TODO:
1. Get nuke dependencies
4. what is the "output_path" arg for nuke render's? (in maya its the root images dir from project settings)
2. What write nodes should be selected when launching the UI? - only those which are selected by the user in nuke
3. implement pyside inheritance for Nuke's window interface
4. Delete dependency manifest after submission?
5. Kevin feedback?
6. Validate that at least one write node is selected
7. Test file pathing on Windows!! especially file_utils manipulations.
'''

class NukeWidget(QtGui.QWidget):

    # The .ui designer filepath
    _ui_filepath = os.path.join(submitter.RESOURCES_DIRPATH, 'nuke.ui')

    def __init__(self, parent=None):
        super(NukeWidget, self).__init__(parent=parent)
        pyside_utils.UiLoader.loadUi(self._ui_filepath, self)
        self.refreshUi()

    def refreshUi(self):
        write_nodes = nuke_utils.get_all_write_nodes()
        self.populateWriteNodes(write_nodes)


    def populateWriteNodes(self, write_nodes):
        '''
        Populate each Write and Deep Write node into the UI QTreeWidget.
        Any write nodes that are currently selected in nuke by the user will be
        also be selected in UI. Note that only write nodes that are selected in 
        the UI will be rendered when submitting to Conductor.
        '''
        self.ui_write_nodes_trwgt.clear()
        assert isinstance(write_nodes, dict), "write_nodes argument must be a dict. Got: %s" % type(write_nodes)
        for write_node, selected in write_nodes.iteritems():
            tree_item = QtGui.QTreeWidgetItem([write_node])
            self.ui_write_nodes_trwgt.addTopLevelItem(tree_item)

            # If the node is selected in Nuke, then select it in the UI
            if selected:
                self.ui_write_nodes_trwgt.setItemSelected(tree_item, True)


    def getSelectedWriteNodes(self):
        '''
        Return the names of the write nodes that are selected in the UI
        '''
        return [item.text(0)for item in self.ui_write_nodes_trwgt.selectedItems()]

    def getUploadOnlyBool(self):
        '''
        Return whether the "Upload Only" checkbox is checked on or off.
        '''
        return self.ui_upload_only.isChecked()


    @QtCore.Slot(bool, name="on_ui_upload_only_toggled")
    def on_ui_upload_only_toggled(self, toggled):
        '''
        when the "Upload Only" checkbox is checked on, disable the Write 
        Nodes widget. when the "Upload Only" checkbox is checked off, enable
        the Write Nodes widget.
        '''
        self.ui_write_nodes_trwgt.setDisabled(toggled)




class NukeConductorSubmitter(submitter.ConductorSubmitter):
    '''
    The class is PySide front-end for submitting Nuke renders to Conductor.
    To launch the UI, simply call self.runUI method.
    
    This class serves as an implemenation example of how one might write a front 
    end for a Conductor submitter for Nuke.  This class is designed to be ripped
    apart of subclassed to suit the specific needs of a studio's pipeline. 
    Have fun :) 
    '''

    _window_title = "Conductor - Nuke"


    @classmethod
    def runUi(cls):
        '''
        Launch the UI
        '''
        ui = cls()
        ui.show()

    def __init__(self, parent=None):
        super(NukeConductorSubmitter, self).__init__(parent=parent)
        self.refreshUi()

    def initializeUi(self):
        super(NukeConductorSubmitter, self).initializeUi()


    def refreshUi(self):
        start, end = nuke_utils.get_frame_range()
        self.setFrameRange(start, end)
        self.extended_widget.refreshUi()


    def getExtendedWidget(self):
        return NukeWidget()


    def generateConductorCmd(self):
        '''
        Return the command string that Conductor will execute
        
        example:
            "nuke-render -X AFWrite.write_exr -F %f /Volumes/af/show/walk/shots/114/114_100/sandbox/mjtang/tractor/nuke_render_job_122/walk_114_100_main_comp_v136.nk"

        '''
        base_cmd = "nuke-render -F %%f %s %s"

        write_nodes = self.extended_widget.getSelectedWriteNodes()
        write_nodes_args = ["-X %s" % write_node for write_node in write_nodes]
        nuke_scriptpath = nuke_utils.get_nuke_script_path()
        cmd = base_cmd % (" ".join(write_nodes_args), nuke_scriptpath)
        return cmd



    def generateDependencyManifest(self, dependency_filepaths):
        '''
        From a given list of filepaths (files which the current Nuke script is 
        dependent upon) generate to a text file which conductor will use to 
        upload the necessary files when executing a render.
        '''

        manifest_filepath = submitter.generate_temporary_filepath()
        return submitter.write_dependency_file(dependency_filepaths, manifest_filepath)


    def collectDependencies(self):
        '''
        Return a list of filepaths that the currently selected Write nodes
        have a dependency on.
        '''

        # A dict of nuke node types, and their knob names to query for dependency filepaths
        dependency_knobs = {'Read':['file'],
                            'DeepRead':['file'],
                            'ReadGeo2':['file'],
                            'Vectorfield':['vfield_file'],
                            'ScannedGrain':['fullGrain'],
                            'Group':['vfield_file', 'cdl_path'],
                            'Precomp':['file'],
                            'AudioRead':['file']}

        write_nodes = self.extended_widget.getSelectedWriteNodes()
        return nuke_utils.collect_dependencies(write_nodes, dependency_knobs)


    def getOutputPath(self):
        '''
        From the selected Write nodes (in the UI), query their output paths
        and derive common directory which they all share (somewhere in their
        directory tree).  Return a two-item tuple, containing the output path, and
        a list of the write node's output paths 
        '''
        write_paths = []
        write_nodes = self.extended_widget.getSelectedWriteNodes()

        for write_node in write_nodes:
            filepath = nuke_utils.get_write_node_filepath(write_node)
            if filepath:
                write_paths.append(filepath)

        output_path = file_utils.get_common_dirpath(write_paths)
        return output_path, write_paths

    def runPreSubmission(self):
        '''
        Override the base class (which is an empty stub method) so that a 
        validation pre-process can be run.  If validation fails, then indicate
        that the the submission process should be aborted.   
        
        We also collect dependencies (and asds) at this point and pass that
        data along...
        In order to validate the submission, dependencies must be collected
        and inspected. Because we don't want to unnessarily collect dependencies
        again (after validation succeeds), we also pass the depenencies along
        in the returned dictionary (so that we don't need to collect them again).
        '''

        raw_dependencies = self.collectDependencies()
        dependencies = file_utils.process_dependencies(raw_dependencies)
        output_path = self.getOutputPath()
        raw_data = {"dependencies":dependencies,
                    "output_path":output_path}

        is_valid = self.runValidation(raw_data)
        return {"abort":not is_valid,
                "dependencies":dependencies,
                "output_path":output_path}



    def runValidation(self, raw_data):
        '''
        This is an added method (i.e. not a base class override), that allows
        validation to occur when a user presses the "Submit" button. If the
        validation fails, a notification dialog appears to the user, halting
        the submission process. 
        
        Validate that the data being submitted is...valid.
        
        1. Dependencies
        2. Output dir
        '''

        # ## Validate that all filepaths exist on disk
        dependencies = raw_data["dependencies"]
        invalid_filepaths = [path for path, is_valid in dependencies.iteritems() if not is_valid]
        if invalid_filepaths:
            message = "Found invalid filepaths:\n\n%s" % "\n\n".join(invalid_filepaths)
            pyside_utils.launch_error_box("Invalid filepaths!", message, parent=self)
            return


        # ## Validate that there is a common root path across all of the Write
        # nodes' output paths
        output_path, write_paths = raw_data["output_path"]
        if not output_path:
            message = "No common/shared output directory. All output files should share a common root!\n\nOutput files:\n    %s" % "\n   ".join(write_paths)
            pyside_utils.launch_error_box("No common output directory!", message, parent=self)
            return

        return True



    def generateConductorArgs(self, data):
        '''
        Override this method from the base class to provide conductor arguments that 
        are specific for Maya.  See the base class' docstring for more details.
        
            cmd: str
            force: bool
            frames: str
            output_path: str # The directory path that the render images are set to output to  
            postcmd: str?
            priority: int?
            resource: int, core count
            skip_time_check: bool?
            upload_dependent: int? jobid?
            upload_file: str , the filepath to the dependency text file 
            upload_only: bool
            upload_paths: list of str?
            usr: str
        '''
        conductor_args = {}
        conductor_args["cmd"] = self.generateConductorCmd()
        conductor_args["cores"] = self.getInstanceType()
        conductor_args["force"] = self.getForceUploadBool()
        conductor_args["frames"] = self.getFrameRangeString()
        conductor_args["output_path"] = data["output_path"]
        conductor_args["resource"] = self.getResource()
        conductor_args["upload_only"] = self.extended_widget.getUploadOnlyBool()

        # if there are any dependencies, generate a dependendency manifest and add it as an argument
        dependency_filepaths = data["dependencies"].keys()
        if dependency_filepaths:
            conductor_args["upload_paths"] = dependency_filepaths

        return conductor_args


    def runConductorSubmission(self, data):

        # If an "abort" key has a True value then abort submission
        if data.get("abort"):
            print "Conductor: Submission aborted"
            return

        super(NukeConductorSubmitter, self).runConductorSubmission(data)

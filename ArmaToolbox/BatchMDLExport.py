import bpy
from bpy_extras.io_utils import ImportHelper, ExportHelper
from . import (
    ArmaTools,
    MDLExporter
)
import os.path as path
import sys


class ArmaToolboxBatchExportConfigProperty(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name="name", description="Name of the config")
    export_it: bpy.props.BoolProperty(name="Export", default=True, description="Include in batch export")

class ATBX_UL_batch_export_checkboxes_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        # Draws the checkbox using the 'export_it' property
        layout.prop(item, "export_it", text=item.name)


class ATBX_PT_batch_export_configs(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Configs"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == "ARMATOOLBOX_OT_batch_export_p3d"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        sfile = context.space_data
        operator = sfile.active_operator

        if len(operator.configs) > 0:
            row = layout.row()
            row.operator("armatoolbox.select_config", text="All").allNone = True
            row.operator("armatoolbox.select_config", text="None").allNone = False

            row = layout.row()
            row.template_list(
                "ATBX_UL_batch_export_checkboxes_list", "",
                operator, "configs",
                operator, "configs_index",
                rows=8 # Sets the height of the scrollbar window
            )


class ATBX_PT_batch_export_options(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Options"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == "ARMATOOLBOX_OT_batch_export_p3d"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "renumberComponents", text="Re-Number Components")
        layout.prop(operator, "applyModifiers")
        layout.prop(operator, "applyTransforms")


class ATBX_OT_select_config(bpy.types.Operator):
    bl_idname = "armatoolbox.select_config"
    bl_label = ""
    bl_description = "Select All/None"

    allNone: bpy.props.BoolProperty(name="allNone")

    def execute(self, context):
        sfile = context.space_data
        operator = sfile.active_operator

        for item in operator.configs:
            item.export_it = self.allNone

        # Keep preset_memory in sync so the next "Save Preset" captures this
        current_active = [c.name for c in operator.configs if c.export_it]
        operator.preset_memory = "||".join(current_active)
        operator.last_memory = operator.preset_memory

        return {"FINISHED"}


class ATBX_OT_p3d_batch_export(bpy.types.Operator):
    """Batch-Export P3D configs"""
    bl_idname = "armatoolbox.batch_export_p3d"
    bl_label = "Batch Export as P3D"
    bl_options = {'PRESET', 'UNDO'}

    directory: bpy.props.StringProperty(
        name="Outdir Path",
        description="Where I will save my stuff",
        subtype='DIR_PATH'
    )

    configs: bpy.props.CollectionProperty(
        description="Configs to export",
        type=ArmaToolboxBatchExportConfigProperty,
        options={'HIDDEN'}  
    )
    
    configs_index: bpy.props.IntProperty(
        name="Configs Index",
        default=0,
        options={'HIDDEN', 'SKIP_SAVE'}
    )

    preset_memory: bpy.props.StringProperty(
        name="Preset Memory",
        default="",
    )

    last_memory: bpy.props.StringProperty(
        default="",
        options={'HIDDEN', 'SKIP_SAVE'}
    )

    renumberComponents: bpy.props.BoolProperty(
        name="Re-Number Components",
        description="Re-Number Geometry Components",
        default=True
    )

    applyModifiers: bpy.props.BoolProperty(
        name="Apply Modifiers",
        description="Apply modifiers before exporting",
        default=True
    )

    applyTransforms: bpy.props.BoolProperty(
        name="Apply all transforms",
        description="Apply rotation, scale, and position transforms before exporting",
        default=True
    )

    filename_ext = "."
    use_filter_folder = True

    @classmethod
    def poll(cls, context):
        return len(context.scene.armaExportConfigs.exportConfigs.keys()) != 0

    def check(self, context):
        scene_configs = context.scene.armaExportConfigs.exportConfigs
        needs_redraw = False

        is_synced = True
        if len(self.configs) != len(scene_configs):
            is_synced = False
        else:
            for i, item in enumerate(scene_configs.values()):
                if self.configs[i].name != item.name:
                    is_synced = False
                    break

        if not is_synced:
            self.configs.clear()
            for item in scene_configs.values():
                x = self.configs.add()
                x.name = item.name
                x.export_it = True
            needs_redraw = True

        if self.preset_memory != self.last_memory:
            active_names = (
                set(self.preset_memory.split("||")) if self.preset_memory else set()
            )
            for c in self.configs:
                c.export_it = c.name in active_names
            self.last_memory = self.preset_memory
            needs_redraw = True

        current_active = [c.name for c in self.configs if c.export_it]
        new_memory = "||".join(current_active)

        if self.preset_memory != new_memory:
            self.preset_memory = new_memory
            self.last_memory = new_memory
            needs_redraw = True

        return needs_redraw

    def invoke(self, context, event):
        # Start fresh every time the dialog opens
        self.configs.clear()
        self.preset_memory = ""
        self.last_memory = ""
        self.check(context)

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        import traceback

        if context.view_layer.objects.active is None and len(context.view_layer.objects) > 0:
            context.view_layer.objects.active = context.view_layer.objects[0]

        exported_files = []

        for item in self.configs:
            if not item.export_it:
                continue

            objs = ArmaTools.GetObjectsByConfig(item.name)
            print("Config: " + item.name)

            if not objs:
                print(f"Warning: No objects found for config {item.name}, skipping.")
                continue

            config = context.scene.armaExportConfigs.exportConfigs[item.name]
            fileName = path.join(self.directory, config.fileName)

            try:
                with open(fileName, "wb") as filePtr:
                    context.view_layer.objects.active = objs[0]
                    MDLExporter.exportObjectListAsMDL(
                        self, filePtr, self.applyModifiers, True, objs,
                        self.renumberComponents, self.applyTransforms,
                        config.originObject
                    )
                exported_files.append(fileName)

            except Exception as inst:
                print(f"--- BATCH EXPORT CRASH ON {item.name} ---")
                traceback.print_exc()
                error_msg = f"Error writing file {fileName} for config {item.name}"
                self.report({'ERROR'}, error_msg)
                return {'CANCELLED'}

        if exported_files:
            print(f"Batch Exporting {len(exported_files)} files to O2Script...")
            ArmaTools.RunO2Script(context, exported_files)

        return {'FINISHED'}


clses = (
    # Properties
    ArmaToolboxBatchExportConfigProperty,
    
    #UI List
    ATBX_UL_batch_export_checkboxes_list,

    # Operators
    ATBX_OT_p3d_batch_export,
    ATBX_OT_select_config,

    # Panels
    ATBX_PT_batch_export_configs,
    ATBX_PT_batch_export_options
)


def register():
    print("BatchMDLExport register")
    from bpy.utils import register_class
    for cs in clses:
        register_class(cs)


def unregister():
    print("BatchMDLExport unregister")
    from bpy.utils import unregister_class
    for cs in clses:
        unregister_class(cs)
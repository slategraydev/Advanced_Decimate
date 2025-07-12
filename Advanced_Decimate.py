# ============================================================
#  Advanced Decimate for Blender
#  Author: Slategray
#  Version: 1.0 | Release Date: 2025-07-12
# ------------------------------------------------------------
#  Description:
#      A one-click Blender script for mesh decimation
#      that preserves shape keys, UVs, vertex groups,
#      materials, and other essential mesh data.
#
#  Repository & Documentation:
#      https://github.com/slategraydev/Advanced_Decimate
# ============================================================

# ============================================================
#  IMPORTS
# ============================================================
import bpy
import numpy as np
import time
import mathutils
import bmesh

# ============================================================
#  REGISTRATION
# ============================================================
bl_info = {
    "name": "Advanced Decimate",
    "author": "Slategray",
    "version": (1, 0),
    "blender": (2, 80, 0),
    "location": "View3D > Sidebar > Tool",
    "description": "Decimates a mesh while preserving shape keys, UVs, vertex groups, and other data.",
    "warning": "",
    "doc_url": "",
    "category": "Object",
}

# ============================================================
#  CORE FUNCTIONS
# ============================================================
def manage_uv_seams(obj, mark_seams=True, original_seams=None):
    """
    Identifies edges on UV island boundaries by checking for UV splits on vertices.
    It is non-destructive to pre-existing seams.
    TODO:
    - It currently marks every edge on a UV seam as a seam.
    - This still works, but it would save some computation time if it worked as intended.
    - This could also be done on a copy of the object instead of trying to preserve the original.
    """
    # Set the active object to the source object.
    bpy.context.view_layer.objects.active = obj

    # Ensure Blender is in object mode before switching to edit mode.
    if bpy.context.object.mode == 'EDIT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.mode_set(mode='EDIT')

    # Get the BMesh of the object.
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    
    # Get the active UV layer.
    uv_layer = bm.loops.layers.uv.active
    if not uv_layer:
        print("INFO: No active UV layer found. Skipping seam marking.")
        bpy.ops.object.mode_set(mode='OBJECT')
        return set() if mark_seams else None

    # To outline the seams mark the edges on the UV island borders.
    if mark_seams:
        print("INFO: Marking UV island borders as temporary seams.")
        original_seams = {e.index for e in bm.edges if e.seam}

        # Commenting this out until the seam marking is more accurate.
        # print(f"INFO: Stored {len(original_seams)} pre-existing seams.")
        
        marked_count = 0
        for edge in bm.edges:
            # I *think* an edge would be on a UV seam if its vertices have different UV coordinates.
            # But, this is currently marking every edge as a seam.
            if not edge.is_boundary:
                vert_uvs = {}
                for loop in edge.link_loops:
                    vert_uvs.setdefault(loop.vert.index, []).append(loop[uv_layer].uv)

                is_seam = False
                for uvs in vert_uvs.values():
                    # If a vertex has more than one distinct UV coordinate, it's a split.
                    if len(uvs) > 1:
                        first_uv = uvs[0]
                        for i in range(1, len(uvs)):
                            if (first_uv - uvs[i]).length > 1e-5:
                                is_seam = True
                                break
                    if is_seam:
                        break
                
                if is_seam:
                    if not edge.seam:
                        marked_count += 1
                    edge.seam = True
        
        print(f"INFO: Marked {marked_count} new edges as seams.")
        bmesh.update_edit_mesh(obj.data)
        bpy.ops.object.mode_set(mode='OBJECT')
        return original_seams

    # If unmarking seams, remove the temporary marked seams.
    else:
        print("INFO: Removing temporary seams from the source mesh.")
        if original_seams is None:
            bpy.ops.object.mode_set(mode='OBJECT')
            return None
        
        removed_count = 0
        for edge in bm.edges:
            # Only remove the seam if it was newly marked by this script.
            # Honestly, it might be better to just remove all seams.
            # While this will preserve the original seams they will be wonky.
            # Keeping this in for now.
            if edge.seam and edge.index not in original_seams:
                edge.seam = False
                removed_count += 1

        # Commenting this out until the seam marking is more accurate.
        # print(f"INFO: Removed {removed_count} temporary seams.")
        bmesh.update_edit_mesh(obj.data)
        bpy.ops.object.mode_set(mode='OBJECT')
        return None

def get_decimation_mapping_kdtree(source_obj, decimate_ratio):
    """
    Get a precise vertex mapping using a KDTree for an exact nearest-neighbor search.
    With this, each vertex on the new mesh will be mapped to the single closest vertex from the original mesh.
    This will help data transfer be more accurate.
    """
    # Create a temporary mesh by copying the source.
    # Create a temporary object to hold the mesh data.
    temp_mesh = source_obj.data.copy()
    temp_mesh.name = "temp_decimate_mesh"
    temp_obj = bpy.data.objects.new("temp_decimate_obj", temp_mesh)
    bpy.context.collection.objects.link(temp_obj)
    
    # Remove shape keys from the temporary object.
    # This prevents the decimate modifier from getting confused.
    if temp_obj.data.shape_keys:
        temp_obj.shape_key_clear()

    # Decimate the temporary mesh, preserving the previously marked seams.
    bpy.context.view_layer.objects.active = temp_obj
    print("INFO: Decimating mesh while preserving UV island borders.")
    mod = temp_obj.modifiers.new(name="Decimate", type='DECIMATE')
    mod.ratio = decimate_ratio
    mod.delimit = {'SEAM'}
    bpy.ops.object.modifier_apply(modifier=mod.name)

    # Create a new mesh from the decimated temporary object.
    decimated_mesh = temp_obj.data.copy()
    decimated_mesh.name = "decimated_mesh_final"

    # Use the original source mesh to build a KDTree for fast spatial lookups.
    source_vertex_count = len(source_obj.data.vertices)
    kdtree = mathutils.kdtree.KDTree(source_vertex_count)
    for i, v in enumerate(source_obj.data.vertices):
        kdtree.insert(v.co, i)
    kdtree.balance()

    # Map each decimated vertex to its closest original vertex.
    vertex_mapping = {}
    for i, v_dec in enumerate(decimated_mesh.vertices):
        co, index, dist = kdtree.find(v_dec.co)
        vertex_mapping[i] = index

    bpy.data.objects.remove(temp_obj, do_unlink=True)
    return vertex_mapping, decimated_mesh

def apply_decimation_mapping_to_shape_key(shape_key_verts, vertex_mapping):
    """
    Apply the decimation mapping to a single shape key's vertex data.
    """
    if not vertex_mapping:
        return np.array([])
        
    decimated_verts_count = max(vertex_mapping.keys()) + 1
    decimated_verts = np.zeros((decimated_verts_count, 3), dtype=np.float32)
    
    # Map the decimated vertices to the original vertices.
    for decimated_idx, original_idx in vertex_mapping.items():
        if original_idx < len(shape_key_verts):
            decimated_verts[decimated_idx] = shape_key_verts[original_idx]
    
    return decimated_verts

def create_final_object_with_mapping(source_obj, shape_key_geometry, key_names, vertex_mapping, decimated_mesh, shape_key_values):
    """
    Create the final object and apply all data using the decimation mapping.
    TODO:
    - Add adjustable user settings for the data transfer modifiers.
    """
    final_obj = bpy.data.objects.new(source_obj.name + "_Decimated", decimated_mesh)
    bpy.context.collection.objects.link(final_obj)
    
    # Ran into some projection issues, need to align the new object to the source object.
    final_obj.matrix_world = source_obj.matrix_world

    # Recreate shape keys using the precise mapping.
    if key_names:
        print("INFO: Recreating the shape keys.")
        # For each shape key, create a new shape key and apply the decimation mapping.
        for i, name in enumerate(key_names):
            shape_key_verts = shape_key_geometry[name]
            new_key = final_obj.shape_key_add(name=name, from_mix=(i == 0)) 
            
            decimated_verts = apply_decimation_mapping_to_shape_key(shape_key_verts, vertex_mapping)
            
            if decimated_verts.size > 0:
                new_key.data.foreach_set('co', decimated_verts.ravel())
                
        # Restore the original shape key values.
        print("INFO: Restoring the shape key values.")
        if final_obj.data.shape_keys:
            final_keys = final_obj.data.shape_keys.key_blocks
            for name, value in shape_key_values.items():
                if name in final_keys:
                    final_keys[name].value = value
    
    # Start the data transfer process.
    print("INFO: Transferring the data from the source mesh.")
    
    # I think the Data Transfer modifier needs the source object to be visible.
    source_obj.hide_set(False)
    bpy.context.view_layer.objects.active = final_obj
    final_obj.select_set(True)

    # Transfer the vertex groups.
    print("INFO: Transferring the vertex groups.")
    vg_data_transfer_mod = final_obj.modifiers.new(name="VGroupTransfer", type='DATA_TRANSFER')
    vg_data_transfer_mod.object = source_obj
    vg_data_transfer_mod.use_vert_data = True
    vg_data_transfer_mod.data_types_verts = {'VGROUP_WEIGHTS'}
    vg_data_transfer_mod.vert_mapping = 'POLYINTERP_NEAREST'
    vg_data_transfer_mod.layers_vgroup_select_src = 'ALL'
    vg_data_transfer_mod.layers_vgroup_select_dst = 'NAME'
    bpy.ops.object.datalayout_transfer(modifier=vg_data_transfer_mod.name)
    bpy.ops.object.modifier_apply(modifier=vg_data_transfer_mod.name)
  
    # Transfer the marked seams.
    print("INFO: Transferring marked seams for UV island borders.")
    seam_transfer_mod = final_obj.modifiers.new(name="SeamTransfer", type='DATA_TRANSFER')
    seam_transfer_mod.object = source_obj
    seam_transfer_mod.use_edge_data = True
    seam_transfer_mod.data_types_edges = {'SEAM'}
    seam_transfer_mod.edge_mapping = 'NEAREST'
    bpy.ops.object.datalayout_transfer(modifier=seam_transfer_mod.name)
    bpy.ops.object.modifier_apply(modifier=seam_transfer_mod.name)
  
    # Transfer the custom normals.
    print("INFO: Transferring custom normals.")
    cn_data_transfer_mod = final_obj.modifiers.new(name="NormalTransfer", type='DATA_TRANSFER')
    cn_data_transfer_mod.object = source_obj
    cn_data_transfer_mod.use_loop_data = True
    cn_data_transfer_mod.data_types_loops = {'CUSTOM_NORMAL'}
    cn_data_transfer_mod.loop_mapping = 'NEAREST_POLYNOR'
    bpy.ops.object.datalayout_transfer(modifier=cn_data_transfer_mod.name)
    bpy.ops.object.modifier_apply(modifier=cn_data_transfer_mod.name)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Link the materials from the source object.
    print("INFO: Linking the materials from the source object.")
    bpy.context.view_layer.objects.active = source_obj
    bpy.ops.object.make_links_data(type='MATERIAL')
    bpy.context.view_layer.objects.active = final_obj

    # Transfer the material assignments.
    print("INFO: Transferring the material assignments.")
    source_bm = bmesh.new()
    source_bm.from_mesh(source_obj.data)
    source_bm.transform(source_obj.matrix_world) 

    # Iterate through the source object's faces and build a KDTree of their centers.
    poly_count = len(source_bm.faces)
    kd = mathutils.kdtree.KDTree(poly_count)
    for i, face in enumerate(source_bm.faces):
        kd.insert(face.calc_center_median(), i)
    kd.balance()

    # Get the target BMesh.
    target_bm = bmesh.new()
    target_bm.from_mesh(final_obj.data)
    target_bm.transform(final_obj.matrix_world)
    target_bm.faces.ensure_lookup_table()
    source_bm.faces.ensure_lookup_table()

    # For each target face, find the closest source face and copy its material index and smooth flag.
    for face in target_bm.faces:
        co, index, dist = kd.find(face.calc_center_median())
        if index is not None:
            source_face = source_bm.faces[index]
            face.material_index = source_face.material_index
            face.smooth = source_face.smooth

    # Write the changes back to the mesh and clean up BMesh data.
    target_bm.to_mesh(final_obj.data)
    source_bm.free()
    target_bm.free()

    # Set the parent and transforms.
    print("INFO: Setting the parent and transforms.")
    if source_obj.parent:
        final_obj.parent = source_obj.parent
        final_obj.parent_type = source_obj.parent_type
    # The world matrix was already set, but parenting could have altered it.
    final_obj.matrix_world = source_obj.matrix_world

    # Recreate the armature modifier if it exists.
    print("INFO: Recreating the armature modifier.")
    for mod in source_obj.modifiers:
        if mod.type == 'ARMATURE' and mod.object:
            armature_mod = final_obj.modifiers.new(name=mod.name, type='ARMATURE')
            armature_mod.object = mod.object

    # Finalize the shading settings from the source object.
    if hasattr(source_obj.data, 'use_auto_smooth'):
        final_obj.data.use_auto_smooth = source_obj.data.use_auto_smooth
        final_obj.data.auto_smooth_angle = source_obj.data.auto_smooth_angle
    
    final_obj.data.update()
    return final_obj

# ============================================================
#  OPERATOR
# ============================================================
class OBJECT_OT_advanced_decimate(bpy.types.Operator):
    """
    The main operator to perform the advanced decimation.
    """
    bl_idname = "object.advanced_decimate"
    bl_label = "Advanced Decimate"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        start_time = time.time()
        
        decimate_ratio = context.scene.adv_decimate_ratio
        
        source_obj = bpy.context.active_object
        if source_obj is None or source_obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a valid mesh object.")
            return {'CANCELLED'}

        # Apply the transforms to the source object.
        print("INFO: Applying the transforms to the source object.")
        bpy.context.view_layer.objects.active = source_obj
        source_obj.select_set(True)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        # Store original visibility to restore it later.
        was_hidden = source_obj.hide_get()
        
        # Mark the seams on the source object so they can be preserved during decimation.
        print("INFO: Marking the seams on the source object.")
        original_seams = manage_uv_seams(source_obj, mark_seams=True)
        
        shape_keys = source_obj.data.shape_keys
        shape_key_geometry = {}
        key_names = []
        shape_key_values = {}

        if shape_keys:
            print("INFO: Reading all shape key geometry.")
            key_names = [key.name for key in shape_keys.key_blocks]
            
            # Directly read the absolute vertex coordinates from each shape key block.
            for key_block in source_obj.data.shape_keys.key_blocks:
                name = key_block.name
                # Store the current value of the shape key.
                shape_key_values[name] = key_block.value
                vertex_count = len(key_block.data)
                coords = np.empty(vertex_count * 3, dtype=np.float32)
                key_block.data.foreach_get('co', coords)
                shape_key_geometry[name] = coords.reshape(-1, 3)

            for key in shape_keys.key_blocks:
                key.value = 0.0
        else:
            print("INFO: No shape keys found on the selected object. Proceeding without shape key data.")

        print("INFO: Performing the decimation.")
        vertex_mapping, decimated_mesh = get_decimation_mapping_kdtree(source_obj, decimate_ratio)
        print(f"INFO: Decimation complete! Mapped {len(source_obj.data.vertices)} source vertices to {len(decimated_mesh.vertices)} decimated vertices.")

        # Need to clean up the temporary seams from the source object,
        # so that only the original seams are transferred.
        print("INFO: Restoring the original seams on the source object before data transfer.")
        manage_uv_seams(source_obj, mark_seams=False, original_seams=original_seams)

        print("INFO: Assembling the final object.")
        final_obj = create_final_object_with_mapping(source_obj, shape_key_geometry, key_names, vertex_mapping, decimated_mesh, shape_key_values)

        # Restore original shape key values on the source object.
        print("INFO: Restoring the original object state.")
        if source_obj.data.shape_keys:
            print("INFO: Restoring the shape key values.")
            source_keys = source_obj.data.shape_keys.key_blocks
            for name, value in shape_key_values.items():
                if name in source_keys:
                    source_keys[name].value = value
        
        # Finalize the script.
        print(f"INFO: Advanced decimation complete in {time.time() - start_time:.2f} seconds!")
        self.report({'INFO'}, f"Generated: '{final_obj.name}'")
        source_obj.hide_set(True)
        return {'FINISHED'}

# ============================================================
#  UI PANEL
# ============================================================
class VIEW3D_PT_advanced_decimate(bpy.types.Panel):
    """
    Creates a Panel in the Object properties window.
    """
    bl_label = "Advanced Decimate"
    bl_idname = "VIEW3D_PT_advanced_decimate"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Tool'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="Decimation Ratio:")
        layout.prop(scene, "adv_decimate_ratio", text="")

        op = layout.operator("object.advanced_decimate", text="Run Decimation")

# ============================================================
#  REGISTRATION
# ============================================================
classes = (
    OBJECT_OT_advanced_decimate,
    VIEW3D_PT_advanced_decimate,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.adv_decimate_ratio = bpy.props.FloatProperty(
        name="Decimate Ratio",
        description="Target ratio for decimation. 0.5 = 50% of original faces.",
        default=0.5,
        min=0.0,
        max=1.0,
        subtype='FACTOR'
    )

def unregister():
    # Unregister in reverse order to respect dependencies.
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
            
    # Also, ensure the scene property exists before trying to delete it.
    if hasattr(bpy.types.Scene, 'adv_decimate_ratio'):
        del bpy.types.Scene.adv_decimate_ratio

# ============================================================
#  MAIN
# ============================================================
if __name__ == "__main__":
    # For my own sanity, I'm unregistering any existing classes first.
    # This allows for re-running the script from the Text Editor.
    for cls in classes:
        # Check bpy.types for a class with the same name.
        if hasattr(bpy.types, cls.__name__):
            bpy.utils.unregister_class(getattr(bpy.types, cls.__name__))
            
    # Unregister the property.
    if hasattr(bpy.types.Scene, 'adv_decimate_ratio'):
        del bpy.types.Scene.adv_decimate_ratio

    register()
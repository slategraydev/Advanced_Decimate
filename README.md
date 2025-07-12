# Advanced Decimate for Blender

A one-click Blender script for mesh decimation that preserves shape keys, UVs, vertex groups, materials, and other essential mesh data.

## Description

This is a simple Blender Add-on that reduces the polygon count of models already populated with data, especially **shape keys**, which are not supported by Blender's standard Decimate modifier.

It does not decimate the original object, it creates a low-poly copy that is instantly exportable.

More features and user facing controls will be added in the future.

## Key Features

-   **Shape Key Preservation**: It (tries) to reconstruct all shape keys on the new, decimated mesh. It's pretty good, but might have some flaws if the decimation ratio is too low.
-   **Non-Destructive Workflow**: The original object is never modified. A new, decimated object is created, and the original is hidden.
-   **Full Data Transfer**: Intelligently transfers and preserves:
    -   UV Maps
    -   Vertex Groups
    -   Material Slots and Assignments
    -   Per-Face Smooth/Flat Shading
    -   Custom Split Normals Data
    -   Armature Modifiers
-   **Simple UI**: A single ratio slider and a button integrated directly into the 3D View's Sidebar.

## Installation

1.  Download the `Advanced_Decimate.py` file from this repository.
2.  In Blender, go to `Edit > Preferences > Add-ons`.
3.  Click the small downward facing arrow at the top-right and select **Install from Disk...**.
4.  Navigate to and select the `Advanced_Decimate.py` file.
5.  Enable/Disable the addon by checking the box next to **"Advanced Decimate"**.

## How to Use

1.  Select the mesh object you wish to decimate.
2.  Open the 3D View Sidebar (press the `N` key if it's hidden).
3.  Navigate to the **Tool** tab.
4.  You will find the **Advanced Decimate** panel there.
5.  Adjust the **Decimation Ratio** slider to your desired value (e.g., `0.5` for 50% of the original face count).
6.  Click the **Run Decimation** button.

The script will run, and a new object named `[YourObject]_Decimated` will be created. Your original object will be hidden from the viewport.

## License

This project is licensed under the AGPL-3.0 License - see the [LICENSE.md](LICENSE.md) file for details. 

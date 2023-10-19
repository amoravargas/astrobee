# GDS_Helper ROS Package Documentation

## Introduction

This document outlines the changes introduced in the commit that enables the use of the `gds_helper` package and its three main components: the `gds_helper` interface, batch mode, and the `gds_simulator`. With these changes, you can now use these components conveniently through the ROS syntax: `rosrun gds_helper <component>`, where `<component>` can be replaced by "interface," "batch," or "gs_tool."

## Commit Details

### 1. Create `gds_helper` Package

In this commit, a new ROS package named `gds_helper` has been created. This package serves as the central hub for the various components necessary for guest scientists working with Astrobee. This separation is a part of the effort to make it easier for guest scientists to utilize the tools.

### 2. Remove `gds_simulator` Folder

The `gds_simulator` folder has been removed from the `astrobee_ops` repository, and its functionality has been integrated into the `gds_helper` package. This integration ensures that all the required tools are available within a single package, simplifying the overall structure.

### 3. Integration of `gds_simulator` into `gds_helper`

The `gds_simulator` component has been integrated into the `gds_helper` package. This integration is aimed at enhancing the accessibility and usability of the simulator for guest scientists. By having the simulator within the same package, it becomes easier to manage and use for testing and simulation purposes.

### 4. Introduction of Bash Scripts

To facilitate the execution of the `gds_helper` components, three Bash scripts have been introduced. These scripts are:

- **`interface`**: This script is used to execute the `gds_helper.py` component, providing an interface for interacting with Astrobee.

- **`batch`**: The `gds_helper_batch.py` component can be executed using this script. It allows users to run `gds_helper` in batch mode, which is useful for automating certain tasks.

- **`gs_tool`**: The `gds_simulator.py` component can be executed with this script. It provides access to the `gds_simulator` functionality.

## Using `gds_helper`

Now that the `gds_helper` package is set up, you can conveniently access its components using ROS commands. Below are the available options:

### Running the `gds_helper` Interface

To run the `gds_helper` interface, use the following command:

```bash
rosrun gds_helper interface
```

This command will start the interface, allowing you to interact with Astrobee.

### Running `gds_helper` in Batch Mode

For batch processing with `gds_helper`, use the following command:

```bash
rosrun gds_helper batch
```

This will execute `gds_helper` in batch mode, making it suitable for automating processing tasks.

### Running the `gds_simulator`

To use the `gds_simulator` tool, execute the following command:

```bash
rosrun gds_helper gs_tool
```

This command launches the `gds_simulator` component for simulation and testing purposes.

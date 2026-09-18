xemu-nxdk_pgraph_tests_results
===

Output of abaire/nxdk_pgraph_tests on various versions of [xemu](xemu.app)

[Browsable on GitHub pages](https://xemu-project.github.io/xemu-nxdk_pgraph_tests_results/)

*Note*: web-display of output may not always match the visible output from the
tests.
In particular, the framebuffer captures in this repository will respect alpha
values in a
way that may not match what is seen within the emulator.

# Checking out on Windows

This repository requires long path support on Windows.

1. In PowerShell with admin privileges: `New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force`
2. In PowerShell with admin privileges: `git config --system core.longpaths true`

# Updating

1. Download the latest UserScripts release from https://github.com/xemu-project/xemu-nxdk_pgraph_tests_results/releases
2. Run the "run.bat" or "run.sh" script with the appropriate arguments below

## Running tests for a new xemu (or nxdk_pgraph_tests) release

* You will need to provide your own BIOS and MCPX boot images.
* The test procedure can take a very long time (more than 60 minutes, unless you use sharding; use the run script with "--help").

### Test the latest xemu with the latest nxdk_pgraph_tests

```shell
./run.sh -B <path_to_bios> -M <path_to_mcpx>
```

  or

```shell
./run.sh -T <path_to_xemu.toml_file>
```

### Testing against specific xemu and/or nxdk_pgraph_tests

```shell
./run.sh \
  -B <path_to_bios> \
  -M <path_to_mcpx> \
  --xemu-tag v0.8.7 \
  --pgraph-tag v2025-02-04_12-54-35-248456211
```

## Reusing the nxdk_pgraph_tests ISO and/or xemu binary

You can use the `--iso` and `--xemu` flags to specify existing artifacts. This
will skip an automated check against the GitHub API for the `latest` tagged
artifacts.

## Submitting new results

Use git to create a new branch, add the generated files, and create a pull
request.

```shell
git checkout -b my_new_results
git add .
git commit -m "xemu v1.2.3 - Windows NVIDIA"
git push origin my_new_results
```

(Updating the commit -m message as appropriate for your test machine)

Then create a new pull request
on [the GitHub project page](https://github.com/xemu-project/xemu-nxdk_pgraph_tests_results)


# Advanced

## Generating diffs

You will need to
install [perceptualdiff](https://github.com/myint/perceptualdiff)

### Compare to the latest [Xbox hardware goldens](https://github.com/abaire/nxdk_pgraph_tests_golden_results)

*Note*: This repository contains a GitHub Action that will perform the hardware
comparison on new results after they are merged to the `main` branch.

```shell
./dev_scripts/compare.py <results_directory_created_by_execute>
```

### Compare between xemu versions or host machines

```shell
./dev_scripts/compare.py <results_directory_created_by_execute> --against <another_results_directory_created_by_execute>
```

# Running locally for xemu development purposes

The `dev_scripts/generate_local_site_for_custom_xemu_build.sh` script may be used to
generate a local variant of
the [deployed pages](https://xemu-project.github.io/xemu-nxdk_pgraph_tests_results/)
that compares a developer build of xemu to the newest checked in results.

import subprocess
import os
from gemstone.common.configurable import ConfigRegister


def run_yosys_script(script, yosys_path="yosys"):
    """Run a Yosys script and return the output."""
    # Check if yosys is installed
    try:
        subprocess.run(
            [yosys_path, "-h"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        raise FileNotFoundError(
            "Could not find yosys. Please install yosys using scripts/setup_yosys.sh."
        )

    cmd = [yosys_path, "-ql", "/dev/stdout", "-s", "/dev/stdin"]

    print("Running Yosys script...")
    p = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = p.communicate(script.encode("utf-8"))

    # Make sure output has no errors
    if "ERROR" in stdout.decode("utf-8"):
        raise RuntimeError(stdout.decode("utf-8"))
    if "ERROR" in stderr.decode("utf-8"):
        raise RuntimeError(stderr.decode("utf-8"))

    print(stdout.decode("utf-8"))

    print("Finished running Yosys script.")


def sv2v(sv_filename, v_filename, sv2v_path="sv2v"):
    """Convert a SystemVerilog file to Verilog using sv2v."""
    # Check if sv2v is installed
    try:
        subprocess.run(
            [sv2v_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        raise FileNotFoundError(
            "Could not find sv2v. Please install sv2v using scripts/setup_sv2v.sh."
        )

    cmd = [sv2v_path, sv_filename]

    print("Running sv2v on " + sv_filename + "...")
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate()

    # create filename in directory of this file
    print("Done running sv2v on " + sv_filename + ".")
    print("Writing output to " + v_filename + "...")
    with open(v_filename, "w") as f:
        f.write(stdout.decode("utf-8"))


def mem_tile_to_btor(
    app_dir="/aha/",
    garnet_filename="/aha/garnet/garnet.v",
    memtile_filename="/aha/garnet/garnet.v",
    mem_tile_module="strg_ub_vec_flat",
    btor_filename="mem_core.btor2",
):
    """Convert a memory tile to a BTOR2 file."""
    # Check if garnet_filename exists
    try:
        with open(garnet_filename, "r") as f:
            pass
    except FileNotFoundError:
        raise FileNotFoundError(f"Could not find {garnet_filename}")

    try:
        with open(memtile_filename, "r") as f:
            pass
    except FileNotFoundError:
        raise FileNotFoundError(f"Could not find {memtile_filename}")

    sv2v_garnet_filename = (
        app_dir + "/" + os.path.basename(garnet_filename).replace(".sv", ".v")
    )
    sv2v_memtile_filename = (
        app_dir + "/" + os.path.basename(memtile_filename).replace(".sv", ".v")
    )

    try:
        with open(sv2v_garnet_filename, "r") as f:
            pass
    except FileNotFoundError:
        sv2v(garnet_filename, sv2v_garnet_filename)

    # try:
    #     with open(sv2v_memtile_filename, "r") as f:
    #         pass
    # except FileNotFoundError:
    sv2v(memtile_filename, sv2v_memtile_filename)

    script = f"""
read -formal {sv2v_memtile_filename} {sv2v_garnet_filename} 

prep -top {mem_tile_module};

hierarchy -check;

chformal -assume -early;

memory -nomap; 
#opt -full;
clean -purge;

flatten; 
#opt -full;
clean -purge;

clk2fflogic;
opt -full;

clean -purge;

setundef -undriven -expose; 
opt -full;

write_verilog {btor_filename}.v
write_btor {btor_filename}            
    """
    run_yosys_script(script)
    print(f"Finished writing BTOR2 file to {btor_filename}")


def garnet_to_btor(
    app_dir="/aha/",
    garnet_filename="/aha/garnet/garnet",
    garnet_tile_module="Interconnect",
    btor_filename="garnet.btor2",
):
    """Convert a memory tile to a BTOR2 file."""
    # Check if garnet_filename exists
    try:
        with open(garnet_filename, "r") as f:
            pass
    except FileNotFoundError:
        raise FileNotFoundError(f"Could not find {garnet_filename}")

    # sv2v_garnet_filename = (
    #     app_dir + "/" + os.path.basename(garnet_filename).replace(".sv", ".v")
    # )

    # # try:
    # #     with open(sv2v_garnet_filename, "r") as f:
    # #         pass
    # # except FileNotFoundError:
    # sv2v(garnet_filename, sv2v_garnet_filename)

    script = f"""
read -formal {garnet_filename} 
prep -top {garnet_tile_module};

hierarchy -check;

chformal -assume -early;

memory -nomap; 

clk2fflogic;

opt -full;
clean -purge;

write_verilog {btor_filename}.v
write_btor {btor_filename}            
"""

    print(script)
    run_yosys_script(script)
    print(f"Finished writing BTOR2 file to {btor_filename}")


def flatten_garnet(
    app_dir="/aha/",
    garnet_filename="/aha/garnet/garnet.v",
    garnet_tile_module="Interconnect",
    garnet_flattened="/aha/garnet/garnet_flattened",
):
    """Convert a memory tile to a BTOR2 file."""
    # Check if garnet_filename exists
    try:
        with open(garnet_filename, "r") as f:
            pass
    except FileNotFoundError:
        raise FileNotFoundError(f"Could not find {garnet_filename}")

    sv2v_garnet_filename = (
        app_dir + "/" + os.path.basename(garnet_filename).replace(".sv", ".v")
    )

    try:
        with open(sv2v_garnet_filename, "r") as f:
            pass
    except FileNotFoundError:
        sv2v(garnet_filename, sv2v_garnet_filename)

    script = f"""
read -formal {sv2v_garnet_filename} /aha/garnet/peak_core/CW_fp_add.v /aha/garnet/peak_core/CW_fp_mult.v
hierarchy -top {garnet_tile_module}
proc
flatten;
setundef -undriven -expose
opt -full;
clean -purge;
write_verilog {garnet_flattened}
    """
    run_yosys_script(script)
    print(f"Finished writing flattened verilog file to {garnet_flattened}")

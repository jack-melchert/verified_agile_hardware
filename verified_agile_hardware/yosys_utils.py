import subprocess
import os


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

    print("Finished running Yosys script.")


def sv2v(sv_filename, sv2v_path="sv2v"):
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
    filename = os.path.join(os.path.dirname(__file__), "../examples/sv2v_output.v")
    print("Done running sv2v on " + sv_filename + ".")
    print("Writing output to " + filename + "...")
    with open(filename, "w") as f:
        f.write(stdout.decode("utf-8"))

    return filename


def mem_tile_to_btor(
    garnet_filename="/aha/garnet/garnet.v",
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

    sv_filename = sv2v(garnet_filename)

    # Check if sv_filename exists
    try:
        with open(sv_filename, "r") as f:
            pass
    except FileNotFoundError:
        raise FileNotFoundError(f"Could not find {sv_filename}, sv2v failed.")

    script = f"""
# read in the file(s) -- there can be multiple
# whitespace separated files, and you can
# escape new lines if necessary
read -formal {sv_filename}

# prep does a conservative elaboration
# of the top module provided
prep -top {mem_tile_module};

# this command just does a sanity check
# of the hierarchy
hierarchy -check;

# If an assumption is flopped, you might
# see strange behavior at the last state
# (because the clock hasn't toggled)
# this command ensures that assumptions
# hold at every state
chformal -assume -early;

# this processes memories
# nomap means it will keep them as arrays
memory -nomap;

# flatten the design hierarchy
flatten;

# (optional) uncomment and set values to simulate reset signal
# use -resetn for an active low pin
# -n configures the number of cycles to simulate
# -rstlen configures how long the reset is active (recommended to keep it active for the whole simulation)
# -w tells it to write back the final state of the simulation as the initial state in the btor2 file
# another useful option is -zinit which zero initializes any uninitialized state
# sim -clock <clockpin> -reset <resetpin> -n <number of cycles> -rstlen <number of cycles> -w <top_module>

# (optional) use an "explicit" clock
# e.g. every state is a half cycle of the
# fastest clock
# use this option if you see errors that
# refer to "adff" or asynchronous components
# IMPORTANT NOTE: the clocks are not
# automatically toggled if you use this option
clk2fflogic;

# This turns all undriven signals into
# inputs
setundef -undriven -expose;


#write_rtlil

# This writes to a file in BTOR2 format
write_btor {btor_filename}            
    """

    run_yosys_script(script)
    print(f"Finished writing BTOR2 file to {btor_filename}")

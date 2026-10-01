#!/usr/bin/env python3
"""
Script to read all registers from peripherals using nrfutil.
Parses the SVD file to extract register addresses and reads them via nrfutil device read.
 
Supports both legacy Nordic SVDs (nRF52/nRF53 with plain peripheral names)
and newer SVDs (nRF54 with GLOBAL_*_S naming convention).

NOTE: By default, registers with all 0x00 or 0xFF values are hidden.
      Use --show_00 or --show_ff flags to display them.
"""
 
import argparse
import re
import xml.etree.ElementTree as ET
import subprocess
import sys
from pathlib import Path
from datetime import datetime


def filter_ns_peripherals(peripherals, show_ns=False):
    """
    Filter out _NS peripherals if a corresponding _S version exists.
    
    Args:
        peripherals: List of peripheral names
        show_ns: If True, do not filter out _NS peripherals
    
    Returns:
        Filtered list with _NS peripherals removed if _S exists (unless show_ns=True)
    """
    if show_ns:
        # Don't filter if user wants to see _NS peripherals
        return peripherals
    
    # Create a set for fast lookup
    peripheral_set = set(peripherals)
    filtered = []
    
    for periph in peripherals:
        # Check if this is a _NS peripheral
        if periph.endswith('_NS'):
            # Get the base name and check if _S version exists
            base_name = periph[:-3]  # Remove _NS
            s_version = base_name + '_S'
            if s_version in peripheral_set:
                # Skip this _NS peripheral because _S exists
                continue
        filtered.append(periph)
    
    return filtered


def halt_device(serial_number=None):
    """
    Halt the device using nrfutil device halt.
    
    Args:
        serial_number: Optional serial number for target device
    
    Returns:
        True if successful, False otherwise
    """
    cmd = ["nrfutil", "device", "halt"]
    
    if serial_number:
        cmd.extend(["--serial-number", serial_number])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            print(f"WARNING: Failed to halt device: {result.stderr.strip()}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("WARNING: Halt command timed out")
        return False
    except Exception as e:
        print(f"WARNING: Error halting device: {e}")
        return False


def check_connected_devices():
    """
    Check how many devices are connected via nrfutil.
    
    Returns:
        Tuple of (device_count, devices_list)
        devices_list is a list of dictionaries with 'serial_number' and 'product' keys
    """
    cmd = ["nrfutil", "device", "list"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return 0, []
        
        # Parse the output to find devices
        # Expected format:
        # 1057787236
        # Product         J-Link
        # ...
        # (blank line between devices)
        devices = []
        lines = result.stdout.strip().splitlines()
        current_serial = None
        current_product = None
        
        for line in lines:
            line = line.strip()
            if not line:
                # Blank line - save current device if we have one
                if current_serial:
                    devices.append({'serial_number': current_serial, 'product': current_product or 'Unknown'})
                    current_serial = None
                    current_product = None
                continue
            
            # Check if line is just a serial number (all digits)
            if line.isdigit() and len(line) >= 8:
                current_serial = line
            elif line.startswith('Product'):
                parts = line.split(None, 1)
                if len(parts) >= 2:
                    current_product = parts[1].strip()
        
        # Don't forget the last device if file doesn't end with blank line
        if current_serial:
            devices.append({'serial_number': current_serial, 'product': current_product or 'Unknown'})
        
        return len(devices), devices
    except Exception:
        return 0, []


def discover_peripherals(svd_file, prefix_filter=None, include_ns=False):
    """
    Scan SVD file and discover peripherals that have registers.
 
    Auto-detects SVD style:
      - If GLOBAL_*_S peripherals exist (nRF54-style), returns only those by default.
      - Set include_ns=True to also include _NS peripherals.
      - Otherwise returns all peripherals with registers (nRF52/nRF53-style).
 
    Args:
        svd_file: Path to SVD file
        prefix_filter: Optional prefix string to restrict discovery
                       (e.g. "GLOBAL_" or "TIMER").  Overrides auto-detection.
        include_ns: If True, include _NS peripherals for GLOBAL-style SVDs
 
    Returns:
        List of peripheral names
    """
    try:
        tree = ET.parse(svd_file)
        root = tree.getroot()
    except Exception as e:
        print(f"Error parsing SVD file: {e}")
        return []
 
    all_periphs = []
    global_periphs = []
    global_ns_periphs = []
 
    for p in root.findall('.//peripheral'):
        name_elem = p.find('name')
        if name_elem is None or not name_elem.text:
            continue
        name = name_elem.text
 
        # Check usability: has own registers or is derived from another peripheral
        derived_from = p.get('derivedFrom')
        registers_elem = p.find('registers')
        if registers_elem is None and not derived_from:
            continue
 
        all_periphs.append(name)
 
        if name.startswith('GLOBAL_'):
            if name.endswith('_S'):
                global_periphs.append(name)
            elif name.endswith('_NS'):
                global_ns_periphs.append(name)
 
    # Decide which set to return
    if prefix_filter:
        # Explicit filter overrides auto-detection
        try:
            pattern = re.compile(prefix_filter, re.IGNORECASE)
            result = [p for p in all_periphs if pattern.search(p)]
        except re.error:
            result = [p for p in all_periphs if prefix_filter in p]
        return sorted(set(result))
 
    if global_periphs:
        # nRF54-style SVD
        if include_ns:
            return sorted(set(global_periphs + global_ns_periphs))
        else:
            return sorted(set(global_periphs))
 
    # nRF52 / nRF53-style SVD — return everything
    return sorted(set(all_periphs))
 
 
def parse_svd_peripheral(svd_file, peripheral_name):
    """
    Parse SVD file and extract peripheral information including base address and all registers.
 
    Args:
        svd_file: Path to SVD file
        peripheral_name: Name of peripheral to extract
 
    Returns:
        Dictionary with base_address and list of registers
    """
    try:
        tree = ET.parse(svd_file)
        root = tree.getroot()
    except Exception as e:
        print(f"Error parsing SVD file: {e}")
        return None
 
    # Find the peripheral
    peripheral = None
    for p in root.findall('.//peripheral'):
        name_elem = p.find('name')
        if name_elem is not None and name_elem.text == peripheral_name:
            peripheral = p
            break
 
    if peripheral is None:
        print(f"Peripheral {peripheral_name} not found in SVD file")
        return None
 
    # Get base address
    base_addr_elem = peripheral.find('baseAddress')
    if base_addr_elem is None:
        print(f"Base address not found for {peripheral_name}")
        return None
 
    base_address = int(base_addr_elem.text, 16)
 
    # Check if peripheral is derived from another
    derived_from = peripheral.get('derivedFrom')
 
    registers = []
 
    # If derived, we need to get registers from the parent peripheral
    if derived_from:
        parent_peripheral = None
        for p in root.findall('.//peripheral'):
            name_elem = p.find('name')
            if name_elem is not None and name_elem.text == derived_from:
                parent_peripheral = p
                break
 
        if parent_peripheral is not None:
            registers = extract_registers(parent_peripheral)
    else:
        registers = extract_registers(peripheral)
 
    return {
        'name': peripheral_name,
        'base_address': base_address,
        'derived_from': derived_from,
        'registers': registers
    }
 
 
def extract_registers(peripheral_elem):
    """
    Extract all registers from a peripheral element.
    Handles both direct registers and clustered registers.
 
    Args:
        peripheral_elem: XML element for the peripheral
 
    Returns:
        List of register dictionaries with name, offset, and description
    """
    registers = []
    registers_elem = peripheral_elem.find('registers')
 
    if registers_elem is None:
        return registers
 
    # Process direct registers
    for reg in registers_elem.findall('register'):
        reg_info = process_register(reg, "")
        if reg_info:
            registers.extend(reg_info)
 
    # Process clustered registers
    for cluster in registers_elem.findall('cluster'):
        cluster_name = cluster.find('name')
        cluster_offset = cluster.find('addressOffset')
        cluster_dim = cluster.find('dim')
        cluster_dim_inc = cluster.find('dimIncrement')
 
        if cluster_name is not None and cluster_offset is not None:
            base_name = cluster_name.text
            base_offset = int(cluster_offset.text, 16)
 
            # Handle dimensioned clusters
            if cluster_dim is not None and cluster_dim_inc is not None:
                dim = int(cluster_dim.text, 16)
                dim_inc = int(cluster_dim_inc.text, 16)
 
                for i in range(dim):
                    cluster_prefix = base_name.replace('[%s]', f'[{i}]')
                    cluster_base_offset = base_offset + (i * dim_inc)
 
                    # Process registers within the cluster
                    for reg in cluster.findall('register'):
                        reg_info = process_register(reg, cluster_prefix, cluster_base_offset)
                        if reg_info:
                            registers.extend(reg_info)
            else:
                # Single cluster
                for reg in cluster.findall('register'):
                    reg_info = process_register(reg, base_name + ".", base_offset)
                    if reg_info:
                        registers.extend(reg_info)
 
    return registers
 
 
def process_register(reg_elem, prefix="", cluster_offset=0):
    """
    Process a single register element and return register info.
    Handles dimensioned registers.
 
    Args:
        reg_elem: XML element for the register
        prefix: Prefix to add to register name (for clustered registers)
        cluster_offset: Base offset for cluster
 
    Returns:
        List of register dictionaries
    """
    reg_name = reg_elem.find('name')
    reg_offset = reg_elem.find('addressOffset')
    reg_desc = reg_elem.find('description')
    reg_access = reg_elem.find('access')
    reg_dim = reg_elem.find('dim')
    reg_dim_inc = reg_elem.find('dimIncrement')
 
    if reg_name is None or reg_offset is None:
        return None
 
    name = reg_name.text
    offset = int(reg_offset.text, 16) + cluster_offset
    description = reg_desc.text if reg_desc is not None else "No description"
    access = reg_access.text if reg_access is not None else "unknown"
 
    registers = []
 
    # Handle dimensioned registers (arrays)
    if reg_dim is not None and reg_dim_inc is not None:
        dim = int(reg_dim.text, 16)
        dim_inc = int(reg_dim_inc.text, 16)
 
        for i in range(dim):
            reg_name_expanded = name.replace('[%s]', f'[{i}]')
            full_name = f"{prefix}{reg_name_expanded}" if prefix else reg_name_expanded
            reg_offset_final = offset + (i * dim_inc)
 
            registers.append({
                'name': full_name,
                'offset': reg_offset_final,
                'description': description,
                'access': access
            })
    else:
        full_name = f"{prefix}{name}" if prefix else name
        registers.append({
            'name': full_name,
            'offset': offset,
            'description': description,
            'access': access
        })
 
    return registers
 
 
def read_memory_block(address, num_bytes, serial_number=None):
    """
    Read a contiguous block of memory using a single nrfutil device read call.

    Args:
        address: Start address (int)
        num_bytes: Number of bytes to read
        serial_number: Optional serial number for target device

    Returns:
        Tuple of (success, dict_or_error)
        On success, dict maps absolute addresses (int) to 32-bit values (int).
    """
    addr_str = f"0x{address:08X}"
    cmd = ["nrfutil", "device", "read", "--direct",
           "--address", addr_str, "--bytes", str(num_bytes)]
    
    if serial_number:
        cmd.extend(["--serial-number", serial_number])
 
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=max(10, num_bytes // 100))
        if result.returncode != 0:
            return False, result.stderr.strip()
 
        # Parse the hex dump output.
        # Typical nrfutil output lines:
        #   0x40000000: 00000001 00000000 ...  |....|
        # Each hex word is a 32-bit register value at consecutive addresses.
        values = {}
        for line in result.stdout.strip().splitlines():
            if ':' not in line:
                continue
            parts = line.split(':', 1)
            try:
                line_addr = int(parts[0].strip(), 16)
            except ValueError:
                continue
            after_colon = parts[1]
            # Strip trailing ASCII representation (after '|')
            if '|' in after_colon:
                after_colon = after_colon[:after_colon.index('|')]
            hex_words = after_colon.split()
            for i, word in enumerate(hex_words):
                try:
                    val = int(word, 16)
                    values[line_addr + i * 4] = val
                except ValueError:
                    continue
 
        return True, values
 
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)
 
 
def main():
    """Main function to read peripheral registers."""
 
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Read all registers from peripherals via nrfutil',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Supported SVD formats:
  nRF54-style (GLOBAL_*_S peripherals) — auto-detected
  nRF52/nRF53-style (plain peripheral names like TIMER0, SPIM0) — auto-detected
 
Examples:
  %(prog)s --svd-file nrf52832.svd --list
  %(prog)s --svd-file nrf52832.svd --peripheral TIMER0
  %(prog)s --svd-file nrf52832.svd --filter "TIMER|SPIM"
  %(prog)s --svd-file nrf52832.svd --all
  %(prog)s --svd-file nrf52832.svd --filter SPIM --only_enable
  %(prog)s --svd-file nrf54l15_application.svd --list
  %(prog)s --svd-file nrf54l15_application.svd --peripheral GLOBAL_DPPIC00_S
  %(prog)s --svd-file nrf54l15_application.svd --filter DPPIC
        """
    )
    parser.add_argument(
        '--show_00',
        action='store_true',
        help='Show registers with all 0x00 values (by default, 0x00000000 registers are hidden)'
    )
    parser.add_argument(
        '--show_ff',
        action='store_true',
        help='Show registers with all 0xFF values (by default, 0xFFFFFFFF registers are hidden)'
    )
    parser.add_argument(
        '--show_more',
        action='store_true',
        help='Display headers, separators, and summaries (default is clean register-only output)'
    )
    parser.add_argument(
        '--show_ns',
        action='store_true',
        help='Show _NS peripherals even when corresponding _S version exists'
    )
    parser.add_argument(
        '--halt',
        action='store_true',
        help='Halt the device before reading registers (executes "nrfutil device halt")'
    )
    parser.add_argument(
        '--output_to_file',
        action='store_true',
        help='Save output to a file named file_<timestamp>.txt'
    )
    parser.add_argument(
        '--only_enable',
        action='store_true',
        help='Read only registers named ENABLE (can be combined with peripheral filters)'
    )
    parser.add_argument(
        '--peripheral',
        type=str,
        help='Specific peripheral name to read (e.g., TIMER0, GLOBAL_DPPIC00_S)'
    )
    parser.add_argument(
        '--filter',
        type=str,
        help='Filter peripherals by regex pattern (e.g., "TIMER" for all timers, "TIMER|EGU" for multiple)'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Read all discovered peripherals (warning: this will be slow!)'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List all available peripherals and exit'
    )
    parser.add_argument(
        '--svd-file',
        type=str,
        required=False,
        help='Path to SVD file (e.g., path/to/nrf52832.svd). If omitted, will auto-detect if only one .svd file exists in current directory'
    )
    parser.add_argument(
        '--serial-number',
        type=str,
        help='Serial number of target device (required when multiple devices are connected)'
    )
    args = parser.parse_args()
 
    # Handle file output redirection if requested
    original_stdout = None
    output_file = None
    output_filename = None
    
    def cleanup_output():
        """Restore stdout and close output file if used."""
        nonlocal output_file, original_stdout, output_filename
        if output_file:
            sys.stdout = original_stdout
            output_file.close()
            print(f"Output saved to: {output_filename}", file=sys.stderr)
    
    if args.output_to_file:
        timestamp_file = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"file_{timestamp_file}.txt"
        try:
            output_file = open(output_filename, 'w', encoding='utf-8')
            original_stdout = sys.stdout
            sys.stdout = output_file
            # Print to stderr so user knows where output is going
            print(f"Output is being saved to: {output_filename}", file=sys.stderr)
        except Exception as e:
            print(f"ERROR: Could not create output file: {e}", file=sys.stderr)
            return 1
 
    # Handle SVD file - auto-detect if not provided
    if args.svd_file:
        svd_file = Path(args.svd_file)
    else:
        # Auto-detect: look for .svd files in current directory
        svd_files = list(Path('.').glob('*.svd'))
        if len(svd_files) == 0:
            print("ERROR: No SVD file specified and no .svd files found in current directory")
            print("       Use --svd-file to specify the SVD file path")
            print()
            print("HINT: SVD files are normally found in:")
            print("      \\modules\\hal\\nordic\\nrfx\\mdk")
            cleanup_output()
            return 1
        elif len(svd_files) == 1:
            svd_file = svd_files[0]
            print(f"Auto-detected SVD file: {svd_file}")
        else:
            print(f"ERROR: Multiple .svd files found in current directory ({len(svd_files)} files)")
            print("       Please specify which one to use with --svd-file")
            print("\nFound:")
            for f in svd_files:
                print(f"  {f}")
            cleanup_output()
            return 1
 
    # Check if SVD file exists (do this early for all commands)
    if not svd_file.exists():
        print(f"ERROR: SVD file not found: {svd_file}")
        cleanup_output()
        return 1
    
    # Check for connected devices (unless just listing peripherals)
    if not args.list:
        device_count, devices = check_connected_devices()
        if device_count == 0:
            print("WARNING: No devices detected via 'nrfutil device list'")
            print("         Make sure a device is connected and nrfutil is configured.")
            print()
        elif device_count > 1:
            if not args.serial_number:
                print("="*80)
                print(f"ERROR: Multiple devices detected ({device_count} devices found)")
                print("       You must specify --serial-number when multiple devices are connected.")
                print("\nConnected devices:")
                for dev in devices:
                    print(f"  Serial: {dev['serial_number']}  |  Product: {dev['product']}")
                print("\nExample:")
                print(f"  python {sys.argv[0]} --svd-file {args.svd_file} --serial-number {devices[0]['serial_number']} --filter CLOCK")
                print("="*80)
                cleanup_output()
                return 1
            else:
                if args.show_more:
                    print(f"Using device with serial number: {args.serial_number}")
                    print()
        
        # Halt device if requested
        if args.halt:
            if args.show_more:
                print("Halting device...")
            success = halt_device(args.serial_number)
            if success:
                if args.show_more:
                    print("Device halted successfully")
                    print()
            else:
                if args.show_more:
                    print("Continuing despite halt failure...")
                    print()
 
    # Handle list command
    if args.list:
        print("Discovering peripherals...")
        peripherals = discover_peripherals(svd_file, include_ns=args.show_ns)
        print(f"\nFound {len(peripherals)} peripherals:\n")
        for p in peripherals:
            print(f"  {p}")
        cleanup_output()
        return 0
 
    # Discover peripherals (auto-detect SVD style)
    all_peripherals = discover_peripherals(svd_file, include_ns=args.show_ns)
 
    if not all_peripherals:
        print("ERROR: No peripherals found in SVD file")
        cleanup_output()
        return 1
 
    # Report detected style
    is_global_style = any(p.startswith('GLOBAL_') for p in all_peripherals)
    if args.show_more:
        if is_global_style:
            print(f"Detected nRF54-style SVD (GLOBAL_*_S peripherals)")
        else:
            print(f"Detected legacy SVD (plain peripheral names)")
 
    # Determine which peripherals to read
    peripherals_to_read = []
 
    if args.peripheral:
        # Read specific peripheral — look it up in ALL peripherals from SVD,
        # not just the auto-detected set, so users can target anything.
        peripherals_in_svd = discover_peripherals(svd_file, prefix_filter=f"^{re.escape(args.peripheral)}$")
        if peripherals_in_svd:
            peripherals_to_read = peripherals_in_svd
        else:
            print(f"ERROR: Peripheral '{args.peripheral}' not found")
            print(f"Use --list to see available peripherals")
            cleanup_output()
            return 1
    elif args.filter:
        # Filter peripherals by pattern — search across ALL peripherals in the SVD
        peripherals_to_read = discover_peripherals(svd_file, prefix_filter=args.filter)
        if not peripherals_to_read:
            print(f"ERROR: No peripherals match filter '{args.filter}'")
            print(f"Use --list to see available peripherals")
            cleanup_output()
            return 1
    elif args.all:
        # Read all peripherals
        peripherals_to_read = all_peripherals
        print(f"WARNING: Reading all {len(peripherals_to_read)} peripherals may take a long time!")
        print("Press Ctrl+C to abort...\n")
    else:
        # Default: show usage
        parser.print_help()
        print(f"\nHint: Use --list to see all available peripherals")
        print(f"      Use --filter TIMER to read all TIMER peripherals")
        cleanup_output()
        return 0
    
    # Filter out _NS peripherals if corresponding _S version exists
    original_count = len(peripherals_to_read)
    peripherals_to_read = filter_ns_peripherals(peripherals_to_read, args.show_ns)
    filtered_count = original_count - len(peripherals_to_read)
    if filtered_count > 0 and args.show_more:
        print(f"Filtered out {filtered_count} _NS peripheral(s) (corresponding _S version exists)")
        if args.show_ns:
            print("  (use --show_ns to display them)")
        print()
 
    # Display filtering info
    if not args.show_00 or not args.show_ff:
        if not args.show_more:
            # Default mode: show as comments
            if not args.show_00 and not args.show_ff:
                print("# NOTE: Registers with 0x00000000 or 0xFFFFFFFF are hidden by default.")
                print("# Use --show_00 or --show_ff to display them.")
            elif not args.show_00:
                print("# NOTE: Registers with 0x00000000 are hidden by default.")
                print("# Use --show_00 to display them.")
            else:
                print("# NOTE: Registers with 0xFFFFFFFF are hidden by default.")
                print("# Use --show_ff to display them.")
            print()
        else:
            # Verbose mode with separator bars
            print("=" * 80)
            if not args.show_00 and not args.show_ff:
                print("NOTE: Registers with 0x00000000 or 0xFFFFFFFF are hidden by default.")
                print("      Use --show_00 or --show_ff to display them.")
            elif not args.show_00:
                print("NOTE: Registers with 0x00000000 are hidden by default.")
                print("      Use --show_00 to display them.")
            else:
                print("NOTE: Registers with 0xFFFFFFFF are hidden by default.")
                print("      Use --show_ff to display them.")
            print("=" * 80)
            print()

    # Process each peripheral
    total_peripherals_processed = 0
    total_success = 0
    total_fail = 0
    total_skipped = 0
    first_peripheral_printed = False  # Track if we've printed any peripheral in default mode
 
    for peripheral_name in peripherals_to_read:
        # In default mode, buffer output to check if we have any registers
        register_output_buffer = []
        
        if args.show_more:
            if len(peripherals_to_read) > 1:
                print("\n" + "=" * 80)

            print(f"Reading registers from {peripheral_name}")
            print(f"SVD file: {svd_file}")
            print("-" * 80)
        # Parse SVD file
        peripheral_info = parse_svd_peripheral(svd_file, peripheral_name)
 
        if peripheral_info is None:
            if args.show_more:
                print(f"ERROR: Could not parse {peripheral_name}")
            continue

        total_peripherals_processed += 1

        if args.show_more:
            print(f"Peripheral: {peripheral_info['name']}")
            print(f"Base Address: 0x{peripheral_info['base_address']:08X}")
            if peripheral_info['derived_from']:
                print(f"Derived from: {peripheral_info['derived_from']}")
        # Filter registers if --only_enable is set
        registers_to_read = peripheral_info['registers']
        if args.only_enable:
            registers_to_read = [reg for reg in registers_to_read if reg['name'] == 'ENABLE']
            if args.show_more:
                print(f"Total ENABLE registers: {len(registers_to_read)}")
        else:
            if args.show_more:
                if not args.show_00 and not args.show_ff:
                    print(f"Total registers: {len(registers_to_read)} (hiding 0x00 and 0xFF values)")
                elif not args.show_00:
                    print(f"Total registers: {len(registers_to_read)} (hiding 0x00 values)")
                elif not args.show_ff:
                    print(f"Total registers: {len(registers_to_read)} (hiding 0xFF values)")
                else:
                    print(f"Total registers: {len(registers_to_read)}")
        if args.show_more:
            print("-" * 80)
 
        # Categorise registers before reading
        readable_regs = []
        skipped_count = 0
        zero_skipped = 0
        ff_skipped = 0

        for reg in registers_to_read:
            if 'TASKS_CHG' in reg['name']:
                skipped_count += 1
            elif reg['access'] == 'write-only':
                skipped_count += 1
            else:
                readable_regs.append(reg)
 
        if not readable_regs:
            if args.show_more:
                print("No readable registers.")
            success_count = 0
            fail_count = 0
            zero_skipped = 0
            ff_skipped = 0
        else:
            # Compute the memory span we need
            base = peripheral_info['base_address']
            min_offset = min(r['offset'] for r in readable_regs)
            max_offset = max(r['offset'] for r in readable_regs)
            block_start = base + min_offset
            block_bytes = (max_offset - min_offset) + 4  # +4 for the last 32-bit register

            if args.show_more:
                print(f"Bulk read: 0x{block_start:08X} – 0x{block_start + block_bytes - 1:08X} ({block_bytes} bytes)")
            success, block_data = read_memory_block(block_start, block_bytes, args.serial_number)

            success_count = 0
            fail_count = 0
            error_tracker = {}  # Track errors: error_message -> count

            if success:
                for reg in readable_regs:
                    full_address = base + reg['offset']
                    if full_address in block_data:
                        value_int = block_data[full_address]
                        # Skip registers with all zeros unless --show_00 is set
                        # Skip registers with all FFs unless --show_ff is set
                        if value_int == 0 and not args.show_00:
                            zero_skipped += 1
                        elif value_int == 0xFFFFFFFF and not args.show_ff:
                            ff_skipped += 1
                        else:
                            register_line = f"{reg['name']} (0x{full_address:08X}) Value: {value_int:08X}"
                            if not args.show_more:
                                register_output_buffer.append(register_line)
                            else:
                                print(register_line)
                        success_count += 1
                    else:
                        error_msg = "address not in bulk read"
                        if error_msg not in error_tracker:
                            # First occurrence - print the full error
                            if args.show_more:
                                print(f"{reg['name']} (0x{full_address:08X}) ERROR: {error_msg}")
                            error_tracker[error_msg] = 1
                        else:
                            # Subsequent occurrence - just count it
                            error_tracker[error_msg] += 1
                        fail_count += 1
                
                # Print summary of repeated errors
                if args.show_more:
                    for error_msg, count in error_tracker.items():
                        if count > 1:
                            print(f"  ... {count - 1} additional register(s) with same error: {error_msg}")
            else:
                error_msg = f"Bulk read failed: {block_data}"
                if args.show_more:
                    print(f"ERROR: {error_msg}")
                fail_count = len(readable_regs)
        
        # In default mode, print peripheral name and registers only if we have output
        if not args.show_more and register_output_buffer:
            # Add blank line before peripheral name (except for first one printed)
            if first_peripheral_printed:
                print()
            print(f"# {peripheral_name}")
            for line in register_output_buffer:
                print(line)
            first_peripheral_printed = True

        if args.show_more:
            print("\n" + "=" * 80)
            summary_parts = [f"{success_count} registers read successfully", f"{fail_count} failed", f"{skipped_count} skipped"]
            if zero_skipped > 0:
                summary_parts.append(f"{zero_skipped} zero-value registers hidden")
            if ff_skipped > 0:
                summary_parts.append(f"{ff_skipped} 0xFF registers hidden")
            print(f"Summary: {', '.join(summary_parts)}")
            print("=" * 80)
 
        total_success += success_count
        total_fail += fail_count
        total_skipped += skipped_count
 
    # Print overall summary if multiple peripherals were processed
    if len(peripherals_to_read) > 1 and args.show_more:
        print("\n" + "#" * 80)
        print(f"OVERALL SUMMARY ({total_peripherals_processed} peripherals processed)")
        print(f"Total registers read: {total_success}")
        print(f"Total failed: {total_fail}")
        print(f"Total skipped: {total_skipped}")
        print("#" * 80)
 
    # Cleanup file output if used
    cleanup_output()
 
    return 0
 
 
if __name__ == "__main__":
    sys.exit(main())
 
 
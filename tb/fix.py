for f in ['vpu_decoder.sv', 'vpu_ram.sv', 'sparseguard.sv']:
    path = '/home/aulia/projects/SparseGuard/rtl/' + f
    with open(path, 'r') as fp:
        lines = fp.readlines()
    if not lines[0].startswith('`'):
        lines[0] = '`default_nettype none\n'
    with open(path, 'w') as fp:
        fp.writelines(lines)

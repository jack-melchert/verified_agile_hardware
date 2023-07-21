from hwtypes.modifiers import strip_modifiers
from peak import family_closure, Peak, family
from peak.mapper.utils import aadt_product_to_dict, SMTForms
from peak.mapper.utils import (
    aadt_product_to_dict,
    rebind_type,
    SMTForms,
    SimplifyBinding,
)
from peak.family import _RegFamily, SMTFamily
from peak.black_box import BlackBox
from collections import defaultdict


def get_aadt(T):
    T = rebind_type(T, family.SMTFamily())
    return family.SMTFamily().get_adt_t(T)


def recursive_filter_fc(obj, cond, fc):
    if cond(obj):
        fc(obj)
    elif hasattr(obj, "__dict__"):
        for _, sub_obj in obj.__dict__.items():
            recursive_filter_fc(sub_obj, cond, fc)


def is_bbox(x):
    return isinstance(x, BlackBox)


def set_bbox_outputs(x):
    output_t = type(x).output_t
    outputs = tuple([family.SMTFamily().BitVector[t().num_bits]() for t in output_t])
    if len(outputs) == 1:
        outputs = outputs[0]
    x._set_outputs(outputs)


def is_reg(x):
    return isinstance(x, _RegFamily.RegBase) or isinstance(x, _RegFamily.AttrRegBase)


def create_input(T):
    stripped_input_t = strip_modifiers(T)
    input_aadt_t = family.SMTFamily().get_adt_t(stripped_input_t)
    input_forms, _, _ = SMTForms()(input_aadt_t)
    return aadt_product_to_dict(input_forms[0].value)


def make_freevar(x):
    x.value = x.value.__class__()


def get_pe_inputs(solver, pe_name):
    input_vars = []
    for i in solver.fts.inputvars:
        if pe_name in str(i):
            input_vars.append(i)

    input_vars = sorted(input_vars, key=lambda x: str(x))
    return input_vars


def get_pe_state(solver, pe_name):
    state_vars = []
    for i in solver.fts.statevars:
        if pe_name in str(i):
            state_vars.append(i)

    state_vars = sorted(state_vars, key=lambda x: str(x))
    return state_vars


def load_pe_tile(solver, PE_fc, pe_name=""):
    PE_smt = PE_fc(family.SMTFamily())

    pe = PE_smt()

    regs = []
    regs_next = []
    recursive_filter_fc(pe, is_reg, make_freevar)
    recursive_filter_fc(pe, is_reg, lambda x: regs.append(x.value))
    recursive_filter_fc(pe, is_bbox, set_bbox_outputs)

    inputs = create_input(PE_smt.input_t)
    outputs = pe(**inputs)

    bboxes = defaultdict(list)

    def record_bbox_io(x):
        bboxes[type(x)].append((x._get_inputs(), x._output_vals))

    recursive_filter_fc(pe, is_reg, lambda x: regs_next.append(x.value))
    recursive_filter_fc(pe, is_bbox, record_bbox_io)

    if not isinstance(outputs, tuple):
        outputs = (outputs,)

    aadt = get_aadt(PE_fc.Py.output_t)
    output_val = aadt.from_fields(*outputs)

    mapping = {}

    for name, val in inputs.items():
        if hasattr(val, "_value_"):
            converted_in = solver.convert(val._value_.value)
        else:
            converted_in = solver.convert(val.value)

        mapping[converted_in] = solver.fts.make_inputvar(
            f"{name}_{pe_name}", converted_in.get_sort()
        )

    o = solver.convert(output_val._value_.value)

    # make pono statevars for all registers
    for reg in regs:
        reg = solver.convert(reg.value)
        statevar = solver.fts.make_statevar(f"{repr(reg)}_{pe_name}", reg.get_sort())
        mapping[reg] = statevar

    # make pono inputvars for all black box outputs
    for op_bboxes in list(bboxes.values()):
        for bbox in op_bboxes:
            outs = bbox[1]
            if not isinstance(outs, tuple):
                outs = (outs,)

            for out in outs:
                out = solver.convert(out.value)
                inputvar = solver.fts.make_inputvar(
                    f"{repr(out)}_{pe_name}", out.get_sort()
                )
                mapping[out] = inputvar

    # solver.convert black box inputs/outputs to corresponding pono/smt-switch terms
    for op_bboxes in list(bboxes.values()):
        for idx in range(len(op_bboxes)):
            ins, outs = op_bboxes[idx]
            if not isinstance(ins, tuple):
                ins = (ins,)
            if not isinstance(outs, tuple):
                outs = (outs,)

            ins = tuple(
                [
                    solver.solver.substitute(solver.convert(x.value), mapping)
                    for x in ins
                ]
            )
            outs = tuple(
                [
                    solver.solver.substitute(solver.convert(x.value), mapping)
                    for x in outs
                ]
            )

            op_bboxes[idx] = (ins, outs)

    # set pono register next values
    for reg, reg_next in zip(regs, regs_next):
        reg = solver.convert(reg.value)
        reg_next = solver.convert(reg_next.value)
        reg_next = solver.solver.substitute(reg_next, mapping)
        solver.fts.assign_next(mapping[reg], reg_next)

    o = solver.solver.substitute(o, mapping)

    return o, bboxes

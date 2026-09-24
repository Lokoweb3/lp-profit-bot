#!/usr/bin/env python3
"""Fail when project bytecode loads a global that its module does not define."""
import builtins
import dis
import importlib
import pkgutil
import types
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import lp_profit_bot


def code_objects(code):
    yield code
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            yield from code_objects(value)


def main():
    failures=[]
    for item in pkgutil.iter_modules(lp_profit_bot.__path__, lp_profit_bot.__name__+'.'):
        module=importlib.import_module(item.name)
        seen=set()
        for value in vars(module).values():
            while getattr(value,'__code__',None) is not None and id(value) not in seen:
                seen.add(id(value));available=set(value.__globals__)|set(vars(builtins))
                for nested in code_objects(value.__code__):
                    for instruction in dis.get_instructions(nested):
                        if instruction.opname in ('LOAD_GLOBAL','LOAD_NAME') and instruction.argval not in available:
                            failures.append(f'{item.name}:{nested.co_name}: {instruction.argval}')
                value=getattr(value,'__wrapped__',None)
    if failures:
        raise SystemExit('Undefined names:\n'+'\n'.join(sorted(set(failures))))
    print('Undefined-name check passed')


if __name__=='__main__':
    main()

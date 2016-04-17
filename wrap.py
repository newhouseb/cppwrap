import clang.cindex
import re
import sys
import os.path

if len(sys.argv) != 4:
        print "Usage `python wrap.py [header to wrap] [prefix to include in c header] [clang library location]`"
        exit(0)

API_PATH = sys.argv[1] #'/Users/ben/src/openvr/headers/openvr.h'
OUTPUT_PATH = os.path.basename(API_PATH).split('.')[0] + '_c.cpp'
OUTPUT_HEADER = os.path.basename(API_PATH).split('.')[0] + '_c.h'

clang.cindex.Config.set_library_path(sys.argv[3]) #'/Users/ben/tools/clang-3.8/lib'
index = clang.cindex.Index.create()
translation_unit = index.parse(API_PATH, ['-x', 'c++'])

from clang.cindex import CursorKind

defined = set()

input_file = open(API_PATH).read()
output = open(OUTPUT_PATH, 'w')
output_header = open(OUTPUT_HEADER, 'w')

def emit(str):
    # print str
    output.write(str + '\n')

def emit_header(str):
    output_header.write(str + '\n')

def flatten_type(spelling, returning=False):
    """Flatten any namespace qualifications into C-compatible declarations"""
    return spelling.split("::")[-1].replace('&', '*' if returning else '')

def flatten_code(code):
    return re.sub(r'([a-zA-Z0-9_]+::)+([a-zA-Z0-9_]+)', r'\2', code)

def traverse(cursor, padding='', ns=[]):
    for child_node in cursor.get_children():
        if child_node.location.file and child_node.location.file.name == API_PATH:
            # Traverse into each namespace and push the namespace to the stack
            if child_node.kind == CursorKind.NAMESPACE:
                traverse(child_node, padding=padding + '  ', ns=ns + [child_node.spelling])

                continue

            # For enum declarations, copypasta the definiton and maybe define constructors?
            if child_node.kind == CursorKind.TYPEDEF_DECL:
                emit_header(flatten_code(input_file[child_node.extent.start.offset:child_node.extent.end.offset] + ';'))

                # Typedef the alias to the C++ namespaced type
                emit("typedef " + '::'.join(ns) + '::' + child_node.spelling + ' ' + child_node.spelling + ';')

                continue

            # For enum declarations, copypasta the definiton and maybe define constructors?
            if child_node.kind == CursorKind.ENUM_DECL:
                emit_header(input_file[child_node.extent.start.offset:child_node.extent.end.offset] + ';')

                # Typedef an alias so that C won't yell and scream
                emit_header('typedef enum ' + child_node.spelling + ' ' + child_node.spelling + ';\n')

                # Typedef the alias to the C++ namespaced type
                emit("typedef " + '::'.join(ns) + '::' + child_node.spelling + ' ' + child_node.spelling + ';')

                continue

            # For struct declarations copypasta the definition and build some constructors?
            if child_node.kind == CursorKind.STRUCT_DECL:
                emit_header(flatten_code(input_file[child_node.extent.start.offset:child_node.extent.end.offset] + ';'))

                # Typedef an alias so that C won't yell and scream
                emit_header('typedef struct ' + child_node.spelling + ' ' + child_node.spelling + ';\n')

                # Typedef the alias to the C++ namespaced type
                emit("typedef " + '::'.join(ns) + '::' + child_node.spelling + ' ' + child_node.spelling + ';')

                continue

            # For static variable definitions, basically just copypasta everything out
            if child_node.kind == CursorKind.VAR_DECL:
                emit_header(input_file[child_node.extent.start.offset:child_node.extent.end.offset] + ';')

                continue

            # If we find a class declaration
            if child_node.kind == CursorKind.CLASS_DECL:

                # Create a C compatible name
                flattened_name = child_node.spelling

                # In the C Header, classes turn into opaque structs
                emit_header('// *********** ')
                emit_header('// ' + flattened_name)
                emit_header('// *********** ')
                emit_header('typedef struct ' + flattened_name + ' ' + flattened_name + ';')

                # In the C++ wrapper, classes turn into flattened type aliases
                emit('typedef ' + '::'.join(ns) + "::" + child_node.spelling + ' ' + flattened_name + ';')

                # Now generate a whole bunch of helper functions for each constructor and method
                for c in child_node.get_children():
                    def get_args(before=[]):
                        args = before + [(flatten_type(c2.type.spelling), c2.spelling) for c2 in c.get_arguments()]
                        return ', '.join([a[0] + ' ' + a[1] for a in args])

                    if c.kind == CursorKind.CONSTRUCTOR:
                        args = [(flatten_type(c2.type.spelling), c2.spelling) for c2 in c.get_arguments()]
                        emit_header(flatten_type(flattened_name) + ' *' + flattened_name + "_New(" + get_args() + ");")

                        emit(flattened_name + ' * ' + flattened_name + '_New(' + get_args() + ') {')
                        emit('    return new ' + flattened_name + '(' + ', '.join([a[1] for a in args[1:]]) + ');')
                        emit('}')
                        emit('')

                    # TODO: Destructors!

                    # TODO: Check if static
                    if c.kind == CursorKind.CXX_METHOD:
                        return_type = c.result_type.spelling
                        return_reference = '&' if '&' in return_type else '';
                        args = [(flattened_name + ' *', 'this_')] + [(flatten_type(c2.type.spelling), c2.spelling) for c2 in c.get_arguments()]

                        emit_header(flatten_type(c.result_type.spelling, returning=True) + '\t' +
                                    flattened_name + '_' + c.spelling + '(' + ', '.join([a[0] + ' ' + a[1] for a in args]) + ');')

                        emit(flatten_type(return_type, returning=True) + ' ' + flattened_name + '_' + c.spelling + '(' + ', '.join([flatten_type(a[0]) + ' ' + a[1] for a in args]) + ') {')
                        emit('    return ' + return_reference + 'this_->' + c.spelling + '(' + ', '.join([a[1] for a in args[1:]]) + ');')
                        emit('}')
                        emit('')

                emit_header('')
                emit_header('')
                emit_header('')

                continue

            # If we find a function declaration
            if child_node.kind == CursorKind.FUNCTION_DECL:

                # Create a C compatible name
                flattened_name = child_node.spelling

                # Ensure we haven't already defiend this when we last saw a forward declaration
                if flattened_name not in defined:
                    args = [(c.type.spelling, c.spelling) for c in child_node.get_arguments()]
                    return_type = child_node.result_type.spelling
                    return_reference = '&' if '&' in return_type else '';

                    emit_header(flatten_type(return_type, returning=True) + ' ' + flattened_name + '(' + ', '.join([flatten_type(a[0]) + ' ' + a[1] for a in args]) + ');')

                    emit(flatten_type(return_type, returning=True) + ' ' + flattened_name + '(' + ', '.join([flatten_type(a[0]) + ' ' + a[1] for a in args]) + ') {')
                    emit('    return ' + return_reference + '::'.join(ns) + '::' + child_node.spelling + '(' + ', '.join([a[1] for a in args]) + ');')
                    emit('}')
                    emit('')
                    defined.add(flattened_name)

                continue

            if child_node.kind == CursorKind.UNEXPOSED_DECL:
                emit_header(input_file[child_node.extent.start.offset:child_node.extent.end.offset] + ';')
                continue

            # Prints things we didn't process yet, for whatever reason
            print child_node.kind, child_node.spelling, input_file[child_node.extent.start.offset:child_node.extent.end.offset]
            print child_node.result_type.spelling, child_node.spelling

emit_header('#include <stdbool.h>')
emit_header('#include <stdint.h>')
emit_header(open(sys.argv[2]).read())

emit('#include "' + os.path.basename(API_PATH) + '"')
emit('extern "C" {')
traverse(translation_unit.cursor)
emit('}')

print "Goodbye"


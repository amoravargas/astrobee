import os
import pty
import re
import subprocess
import traceback
from argparse import Action, ArgumentParser, FileType

import yaml

# from shell_colors import Back, Colors, Fore, Style
from util.shell_colors import Back, Colors, Fore, Style

# Arguments
args = []
kwargs = {}
saved = {}

# Parsing error codes
IO_ERROR = 1
YAML_ERROR = 2
DOC_ERROR = 3
SECTION_ERROR = 4
UNKNOWN_ERROR = 5
ARG_ERROR = 6
UNKNOWN_FORMAT_ERROR = 7


class ParseKwargs(Action):
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, dict())
        for value in values:
            tokens = value.split("=", 1)
            getattr(namespace, self.dest)[tokens[0]] = "".join(tokens[1:])


# Custom tag handlers
def _yaml_join(loader, node):
    seq = loader.construct_sequence(node)
    return "".join([str(i) for i in seq])


def _yaml_eval(loader, node):
    expression = ""
    if isinstance(node, yaml.nodes.SequenceNode):
        input = loader.construct_sequence(node)
        expression = input[0]
        args = input[1:]
        expression = expression % tuple(args)
    elif isinstance(node, yaml.nodes.ScalarNode):
        expression = loader.construct_scalar(node)
    return eval(_replace_all_args(expression))


def _yaml_env(loader, node):
    value = str(loader.construct_scalar(node))
    match = re.compile(".*?\\${(\\w+)}.*?").findall(value)
    if match:
        for key in match:
            if key in os.environ:
                value = value.replace("${%s}" % key, os.environ[key])
        return value
    return value


def _yaml_shell(loader, node):
    value = str(loader.construct_scalar(node))
    proc = subprocess.Popen(
        value,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        shell=True,
    )
    out, err = proc.communicate()
    return out.decode()


def _yaml_ishell(loader, node):
    out = [""]
    reg = "<@d>(.*?)</@d>"

    def _read(fd):
        data = os.read(fd, 1024)
        out[0] += data
        return data

    value = str(loader.construct_scalar(node))
    pty.spawn(["bash", "-c"] + [value], _read)
    chunks = re.findall(reg, out[0])
    return "".join(chunks)


def _yaml_args(loader, node):
    value = str(loader.construct_scalar(node))
    for k in re.findall(".*?\\${(\\w+)}.*?", value):
        if not k.isdigit():
            continue
        k = int(k)
        v = ""
        if k in range(1, len(args) + 1):
            v = str(args[k - 1])
        value = value.replace("${%d}" % k, v)
    return value


def _yaml_kwargs(loader, node):
    value = str(loader.construct_scalar(node))
    for match in re.findall(".*?\\${(\\w+)}.*?", value):
        value = value.replace("${%s}" % match, kwargs.get(match, ""))
    return value


def _yaml_save(loader, node):
    variables = loader.construct_mapping(node)
    saved.update(variables)
    return ""


def _yaml_if(loader, node):
    parts = loader.construct_sequence(node)
    condition = parts[0] if parts[0:] else None
    true_return = parts[1] if parts[1:] else None
    false_return = parts[2] if parts[2:] else ""
    if condition is None or true_return is None:
        return None
    return true_return if eval(_replace_all_args(condition)) else false_return


def _replace_all_args(value):
    for match in re.findall(".*?\\${([0-9]+)}.*?", value):
        try:
            v = args[int(match) - 1]
        except IndexError:
            v = ""
        value = value.replace("${%s}" % match, v)
    for match in re.findall(".*?\\${(\\w+)}.*?", value):
        value = value.replace("${%s}" % match, kwargs.get(match, ""))
    return value


# Register tag handlers
yaml.add_constructor("!join", _yaml_join)
yaml.add_constructor("!eval", _yaml_eval)
yaml.add_constructor("!env", _yaml_env)
yaml.add_constructor("!shell", _yaml_shell)
yaml.add_constructor("!ishell", _yaml_ishell)
yaml.add_constructor("!arg", _yaml_args)
yaml.add_constructor("!kwarg", _yaml_kwargs)
yaml.add_constructor("!save", _yaml_save)
yaml.add_constructor("!if", _yaml_if)


def _dump_traceback():
    # Returns different values in Python2 and 3, but both end in None
    exc = traceback.format_exc()
    if not exc.endswith("None\n"):
        print(exc)


def _print_exception(msg):
    print("%s%s[ EXCEPTION ] %s%s" % (Style.bold, Fore.red, msg, Colors.reset))
    _dump_traceback()


def _print_error(msg):
    print("%s[ ERROR ] %s%s" % (Fore.red, msg, Colors.reset))


def _parse_document(stream, document_idx):
    doc = None
    ret = 0
    try:
        # Split file into documents, remove the header
        # YAML files should have a header showing the YAML version
        # and each document should start with the marker ---
        documents = stream.read().split("---")[1:]
        doc = yaml.load(documents[document_idx], Loader=yaml.Loader)
        # Keep for reference in case we want to go back to this
        # documents = yaml.load_all(stream, Loader=yaml.Loader)
        # doc = next(itertools.islice(documents, document_idx, None))
    except yaml.YAMLError:
        _print_exception("Error parsing YAML file")
        ret = YAML_ERROR
    except StopIteration:
        _print_exception("Document index %d not found" % document_idx)
        ret = DOC_ERROR
    except:
        _print_exception("Unknown error while parsing YAML")
        ret = UNKNOWN_ERROR
    finally:
        return (ret, doc)


def parse_document(stream, document_idx, section=None, iargs=[], ikwargs={}):
    global args, kwargs
    args = iargs
    kwargs = ikwargs
    ret, parsed = _parse_document(stream, document_idx)
    if parsed != None and section != None:
        # Document was parsed and a specific section was requested
        # Check the input parsed to dictionary
        if not isinstance(parsed, dict):
            _print_exception("No section structure found")
            return (UNKNOWN_FORMAT_ERROR, None)
        # Look for section
        parsed = parsed.get(section)
        if parsed is None:
            _print_error('Section "%s" could not be found' % section)
            return (SECTION_ERROR, None)

    return (ret, parsed)


if __name__ == "__main__":
    parser = ArgumentParser(description="Astrobee YAML Parser")
    parser.add_argument("file", type=FileType("r"))
    parser.add_argument("-document", "-d", type=int, default=0)
    parser.add_argument("-section", "-s", default=None)
    parser.add_argument("-args", "-a", default=[], nargs="*")
    parser.add_argument("-kwargs", "-k", default={}, nargs="*", action=ParseKwargs)
    pargs = parser.parse_args()
    ret, parsed = parse_document(
        pargs.file, pargs.document, pargs.section, pargs.args, pargs.kwargs
    )

    if parsed != None:
        print("\n[ YAML1.1 ]\n%s" % parsed)
    exit(ret)

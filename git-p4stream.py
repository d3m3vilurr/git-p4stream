#!/usr/bin/env python
import subprocess
import sys
import os
import time
import tempfile
import argparse

EDITOR = os.environ.get('EDITOR', 'vim')
verbose = False

CHANGE_TEMPLATE = """
Change: new

Client: %(client)s

User: %(user)s

Status: new

Description:
%(desc)s
"""


def die(msg):
    print msg
    sys.exit(1)

def call_editor(default_msg="", prefix=None):
    edited = ""
    with tempfile.NamedTemporaryFile() as f:
        f.write(default_msg)
        f.flush()
        subprocess.call([EDITOR, f.name])
        f.seek(0)
        edited = f.read()
    if prefix:
        edited = '\n'.join(map(lambda x: prefix + x, edited.split('\n')))
    return edited

def write_pipe(cmd, stdin):
    if verbose:
        print cmd
    p = subprocess.Popen(cmd,
                         stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,
                         shell=isinstance(cmd, basestring))
    (out, err) = p.communicate(stdin)
    if p.wait():
        die('Command failed: %s' % cmd)
    return out

def read_pipe(cmd, ignore_error=False):
    if verbose:
        print cmd
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         shell=isinstance(cmd, basestring))
    (out, err) = p.communicate()
    if p.returncode != 0 and not ignore_error:
        die('Command failed: %s' % cmd)
    return out

_git_config = {}

def git_config(tag, multi=False):
    key = "%s__%s" % (tag, multi)
    if _git_config.get(key) != None:
        return _git_config[key]
    cmd = ['git', 'config']
    if multi:
        cmd.append('--get-all')
    else:
        cmd.append('--get')
    cmd.append(tag)
    ret = (read_pipe(cmd, ignore_error=True) or '').strip()
    if multi:
        ret = ret.split('\n')
    _git_config[key] = ret
    return ret

def p4_cmd():
    cmd = ['p4']
    port = git_config('git-p4.port')
    if port:
        cmd += ['-p', port]
    host = git_config('git-p4.host')
    if host:
        cmd += ['-H', host]
    client = git_config('git-p4.client')
    if client:
        cmd += ['-c', client]
    user = git_config('git-p4.user')
    if user:
        cmd += ['-u', user]
    password = git_config('git-p4.password')
    if password:
        cmd += ['-p', password]
    return cmd

def p4_write_pipe(cmd, stdin):
    c = p4_cmd() + cmd
    return write_pipe(c, stdin)

def p4_read_pipe(cmd, ignore_error=False):
    if isinstance(cmd, basestring):
        cmd = [cmd]
    c = p4_cmd() + cmd
    return read_pipe(c, ignore_error)

def p4_client_info():
    return p4_read_pipe(['client', '-o'])

def client_setting(key):
    client = p4_client_info()
    key = key.title()
    if key[-1] != ':':
        key += ':'
    info = filter(lambda x: x.startswith(key), client.split('\n'))
    if not len(info):
        return
    return info[0].split(key)[1].strip()

def git_branch_exists(br):
    rev = read_pipe(['git', 'rev-parse', '-q', '--verify', br],
                    ignore_error=True)
    return not not rev

def git_dir():
    return read_pipe(['git', 'rev-parse', '--git-dir']).strip()

def git_ref(br):
    ref = read_pipe(['git', 'rev-parse', br], ignore_error=True)
    return ref.strip()

def current_p4_branch():
    master_ref = git_ref('p4/master')
    configs = git_config('git-p4stream.maps', multi=True)
    for config in configs:
        types = config.split(':')
        if len(types) == 2:
            types.append(None)
        k, r, v = types
        if master_ref == git_ref('p4/%s' % k):
            return k
    die('Not found matched branch')

def branch_setting(br):
    configs = git_config('git-p4stream.maps', multi=True)
    for config in configs:
        types = config.split(':')
        if len(types) == 2:
            types.append(None)
        k, r, v = types
        if k == br:
            return dict(branch=k, real=r, virtual=v or r)
    die('Not found matched branch')


def describe(change):
    return p4_read_pipe(['describe', '-S', str(change)]).strip()


class Command(object):
    def __init__(self, parser):
        pass

    def run(self, args):
        pass


class Switch(Command):
    def __init__(self, parser):
        parser.add_argument('branch', type=str,
                            help='change branch name')

    def run(self, args):
        # check current client support stream
        if not client_setting('stream'):
            die('Not stream client')
        configs = git_config('git-p4stream.maps', multi=True)
        for config in configs:
            types = config.split(':')
            if len(types) == 2:
                types.append(None)
            k, r, v = types
            if args.branch == k:
                break
        else:
            die('Not found stream-branch map')
        depot = v or r
        print 'Switch to %s' % depot
        # change stream
        p4_read_pipe(['client', '-s', '-S', depot])
        # update last changes
        p4_read_pipe(['sync'], ignore_error=True)
        # change p4/master tree
        #if git_branch_exists('p4/master'):
        #    read_pipe(['git', 'push', '.', ':p4/master'], ignore_error=True)
        ref = 'ref: refs/remotes/p4/%s' % args.branch
        for fn in ('master', 'HEAD'):
            with open(os.path.join(git_dir(),
                                   'refs/remotes/p4/%s' % fn),
                      'w') as f:
                f.write(ref)
        print 'Now p4/master is %s' % args.branch


class Sync(Command):
    def run(self, args):
        setting = branch_setting(current_p4_branch())
        print 'sync remote branch p4/%s ...' % setting['branch']
        work_branch = read_pipe('git rev-parse --abbrev-ref HEAD').strip()
        if work_branch != 'master':
            read_pipe('git checkout master')
        read_pipe('git reset --hard p4/master')
        read_pipe('git p4 rebase')
        if work_branch != 'master':
            read_pipe('git checkout %s' % work_branch)


class ChangeInfo(Command):
    def __init__(self, parser):
        parser.add_argument('changeset', type=int,
                            help='target changeset')

    def run(self, args):
        print describe(args.changeset).split('Differences ...')[0]


class Shelves(Command):
    def __init__(self, parser):
        pass

    def run(self, args):
        setting = branch_setting(current_p4_branch())
        user = git_config('git-p4.user') or os.environ['P4USER']
        changes = p4_read_pipe(['changes', '-s', 'pending', '-u', user]).strip()
        if not changes:
            return
        changes = map(lambda x: x.split()[1], changes.split('\n'))
        for change in changes:
            desc = describe(change)
            shelved = desc.split('Shelved files ...')[-1]
            shelved = shelved.split('Differences ...')[0].strip()
            # first file
            shelved = shelved.split('\n')[0]
            if not shelved:
                pass
            # another branches shelve
            if setting['virtual'] not in shelved:
                pass
            print "%s %s" % (change, desc.split('\n')[2].strip())


class Shelve(Command):
    def __init__(self, parser):
        parser.add_argument('changeset', type=int, nargs='?',
                            #required=False,
                            help='target changeset')

    def run(self, args):
        # first require sync remote repo
        p4_read_pipe('sync')
        # check mergeable
        master = git_ref('p4/master')
        merge_base = read_pipe(['git', 'merge-base', 'p4/master', 'HEAD']).strip()
        if merge_base != master:
            die('Base branch mismatch')
        # fetch commit messages
        logs = read_pipe(['git', 'log', '--reverse', '%s..' % master])
        if not logs:
            die('Empty changes')
        # fetch updated file list
        files = read_pipe(['git', 'diff', '--name-only', '%s..' % master]).strip()
        files = files.split('\n')
        if not files:
            die('Empty changes')
        path = client_setting('root')
        sync = git_config('git-p4stream.sync')
        if sync:
            path = os.path.join(path, sync)
        # file open/delete
        opened = []
        adds = []
        git = git_dir()
        for fn in files:
            p = os.path.join(path, fn)
            opened.append(p)
            if not os.path.exists(p):
                adds.append(p)
                continue
            if os.path.exists(os.path.join(git, '..', fn)):
                cmd = 'open'
            else:
                cmd = 'delete'
            p4_read_pipe([cmd, p])
        # patch files
        patch = read_pipe(['git', 'diff', '%s..' % master])
        try:
            write_pipe(['patch', '-p1', '-fNd', path], patch)
        except:
            pass
        # file add
        for p in adds:
            p4_read_pipe(['add', p])
        # create new changeset
        if not args.changeset:
            setting = branch_setting(current_p4_branch())
            client = git_config('git-p4.client') or os.environ['P4CLIENT']
            user = git_config('git-p4.user') or os.environ['P4USER']
            change_data = CHANGE_TEMPLATE % dict(client=client, user=user,
                                                 desc=call_editor(logs,
                                                                  prefix='\t'))
            out = p4_write_pipe(['change', '-i'], change_data)
            change = out.split()[1]
        else:
            change = str(args.changeset)
        # move file to changeset
        for f in opened:
            p4_read_pipe(['reopen', '-c', change, f])
        # shelve all files
        p4_read_pipe(['shelve', '-c', change, '-r'])
        # TODO: finally action
        for f in opened:
            p4_read_pipe(['revert', f])
            if f in adds:
                os.unlink(f)


class ShelveDelete(Command):
    def __init__(self, parser):
        parser.add_argument('changeset', type=int,
                            help='target changeset')

    def run(self, args):
        p4_read_pipe(['shelve', '-c', str(args.changeset), '-d'])
        p4_read_pipe(['change', '-d', str(args.changeset)])


commands = {
    'switch': Switch,
    'sync': Sync,
    'shelve': Shelve,
    'shelves': Shelves,
    'delete': ShelveDelete,
    'info': ChangeInfo,
}

def helps():
    print 'usage: %s <command> [args]' % sys.argv[0]
    print
    print 'commands: %s' % ', '.join(commands.keys())
    print
    print 'Try %s <command> --help for command specific help.' % sys.argv[0]

def main():
    if not len(sys.argv[1:]):
        helps()
        sys.exit(2)

    cmd_name = sys.argv[1]
    cls = commands.get(cmd_name)
    if not cls:
        helps()
        sys.exit(2)
    parser = argparse.ArgumentParser(prog=('%s %s' % tuple(sys.argv[:2])))
    cmd = cls(parser)
    args = parser.parse_args(sys.argv[2:])
    cmd.run(parser.parse_args(sys.argv[2:]))

if __name__ == '__main__':
    main()

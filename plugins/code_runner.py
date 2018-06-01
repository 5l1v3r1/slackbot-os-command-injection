import time
import tarfile

from io import BytesIO

import docker


class CodeRunner(object):
    def __init__(self, docker_image):
        self.docker_image = docker_image
        self.docker_client = docker.from_env()
        self.create_kwargs = {
            'network': 'none',
            'cpuset_cpus': '0',
            'mem_limit': '128m',
            'memswap_limit': '128m',
            'hostname': 'os-command-injection',
            'pids_limit': 30,
            'ulimits': [{'name': 'fsize', 'soft': int(1e7), 'hard': int(1e7)}]
        }

    def _put_source_code(self, container, filename, source_code):
        file_data = source_code.encode('utf8')
        pw_tarstream = BytesIO()
        pw_tar = tarfile.TarFile(fileobj=pw_tarstream, mode='w')
        tarinfo = tarfile.TarInfo(name=filename)
        tarinfo.size = len(file_data)
        tarinfo.mtime = time.time()
        # tarinfo.mode = 0600
        pw_tar.addfile(tarinfo, BytesIO(file_data))
        pw_tar.close()
        pw_tarstream.seek(0)

        with pw_tarstream as archive:
            container.put_archive('/tmp/workspace', archive)

    def _readlines_tarfile(self, tf, fname):
        try:
            lines = tf.extractfile(fname).readlines()
            lines = '\n'.join([x.decode('utf8').strip() for x in lines])
            return lines.strip()
        except KeyError:
            return ''

    def _get_results(self, container):
        stream, _ = container.get_archive('/tmp/dist')
        raw_data = next(stream)
        with tarfile.open(fileobj=BytesIO(raw_data), mode='r') as tf:
            stdout = self._readlines_tarfile(tf, 'dist/stdout.txt')
            stderr = self._readlines_tarfile(tf, 'dist/stderr.txt')
            running_time = self._readlines_tarfile(tf, 'dist/time.txt')

            compile_stdout = self._readlines_tarfile(
                tf, 'dist/compile_stdout.txt')
            compile_stderr = self._readlines_tarfile(
                tf, 'dist/compile_stderr.txt')
            compile_time = self._readlines_tarfile(tf, 'dist/compile_time.txt')

        return {
            'run': (stdout, stderr, running_time),
            'compile': (compile_stdout, compile_stderr, compile_time)
        }

    def _create_command(self, base_cmd, timeout, file_prefix=''):
        cmd = ('/usr/bin/time -q -f %e '
               '-o /tmp/dist/{prefix}time.txt '
               'timeout {timeout} '
               '{base_cmd} '
               '> /tmp/dist/{prefix}stdout.txt '
               '2> /tmp/dist/{prefix}stderr.txt')
        return cmd.format(base_cmd=base_cmd,
                          timeout=timeout, prefix=file_prefix)

    def run(self, source_code, docker_tag, filename,
            compile_cmd, run_cmd, **kwargs):
        client = self.docker_client

        compile_cmd = 'bash -c \\"{}\\"'.format(compile_cmd)
        compile_cmd = self._create_command(compile_cmd, 30, 'compile_')
        run_cmd = self._create_command(run_cmd, 15)

        cmd = '{} && {}'.format(compile_cmd, run_cmd)

        docker_image = '{}:{}'.format(self.docker_image, docker_tag)
        container = client.containers.create(
            docker_image, 'bash -c "{}"'.format(cmd), **self.create_kwargs)

        self._put_source_code(container, filename, source_code)

        container.start()
        container.wait()

        results = self._get_results(container)

        return results


if __name__ == '__main__':
    code_runner = CodeRunner('odanado/os-command-injection')
    src_code = """
    echo hoge
    """

    results = code_runner.run(
        src_code, 'bash',
        'Main.sh', "cat Main.sh | tr -d '\\r' > a.out", "bash a.out")

    print(results)

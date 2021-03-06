import asyncio
import binascii
import ctypes
import hashlib
import os
import pathlib
import shutil
import sys
from datetime import datetime

import pytest

import py7zr
from py7zr import unpack_7zarchive
from py7zr.exceptions import UnsupportedCompressionMethodError
from py7zr.helpers import UTC

from . import aio7zr, decode_all

testdata_path = os.path.join(os.path.dirname(__file__), 'data')
os.umask(0o022)


def check_archive(archive, tmp_path):
    assert sorted(archive.getnames()) == ['test', 'test/test2.txt', 'test1.txt']
    expected = []
    expected.append({'filename': 'test'})
    expected.append({'lastwritetime': 12786932616, 'as_datetime': datetime(2006, 3, 15, 21, 43, 36, 0, UTC()),
                     'filename': 'test/test2.txt'})
    expected.append({'lastwritetime': 12786932628, 'as_datetime': datetime(2006, 3, 15, 21, 43, 48, 0, UTC()),
                     'filename': 'test1.txt'})
    for i, cf in enumerate(archive.files):
        assert cf.filename == expected[i]['filename']
        if not cf.is_directory:
            assert cf.lastwritetime // 10000000 == expected[i]['lastwritetime']
            assert cf.lastwritetime.as_datetime().replace(microsecond=0) == expected[i]['as_datetime']
    archive.extractall(path=tmp_path)
    assert tmp_path.joinpath('test/test2.txt').open('rb').read() == bytes('This file is located in a folder.', 'ascii')
    assert tmp_path.joinpath('test1.txt').open('rb').read() == bytes('This file is located in the root.', 'ascii')
    archive.close()


@pytest.mark.files
def test_solid(tmp_path):
    f = 'solid.7z'
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, '%s' % f), 'rb'))
    check_archive(archive, tmp_path)


@pytest.mark.files
def test_empty():
    # decompress empty archive
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'empty.7z'), 'rb'))
    assert archive.getnames() == []


@pytest.mark.files
def test_github_14(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'github_14.7z'), 'rb'))
    assert archive.getnames() == ['github_14']
    archive.extractall(path=tmp_path)
    with tmp_path.joinpath('github_14').open('rb') as f:
        assert f.read() == bytes('Hello GitHub issue #14.\n', 'ascii')


@pytest.mark.files
def _test_umlaut_archive(filename: str, target: pathlib.Path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, filename), 'rb'))
    assert sorted(archive.getnames()) == ['t\xe4st.txt']
    archive.extractall(path=target)
    archive.close()
    actual = target.joinpath('t\xe4st.txt').open().read()
    assert actual == 'This file contains a german umlaut in the filename.'


@pytest.mark.files
def test_non_solid_umlaut(tmp_path):
    # test loading of a non-solid archive containing files with umlauts
    _test_umlaut_archive('umlaut-non_solid.7z', tmp_path)


@pytest.mark.files
def test_solid_umlaut(tmp_path):
    # test loading of a solid archive containing files with umlauts
    _test_umlaut_archive('umlaut-solid.7z', tmp_path)


@pytest.mark.files
def test_bugzilla_4(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'bugzilla_4.7z'), 'rb'))
    expected = [{'filename': 'History.txt', 'mtime': 1133704668, 'mode': 33188,
                 'digest': '46b08f0af612371860ab39e3b47666c3bd6fb742c5e8775159310e19ebedae7e'},
                {'filename': 'License.txt', 'mtime': 1105356710, 'mode': 33188,
                 'digest': '4f49a4448499449f2864777c895f011fb989836a37990ae1ca532126ca75d25e'},
                {'filename': 'copying.txt', 'mtime': 999116366, 'mode': 33188,
                 'digest': '2c3c3ef532828bcd42bb3127349625a25291ff5ae7e6f8d42e0fe9b5be836a99'},
                {'filename': 'readme.txt', 'mtime': 1133704646, 'mode': 33188,
                 'digest': '84f2693d9746e919883cf169fc83467be6566d7501b5044693a2480ab36a4899'}]
    decode_all(archive, expected, tmp_path)


@pytest.mark.files
def test_bugzilla_16(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'bugzilla_16.7z'), 'rb'))
    expected = [{'filename': 'mame4all_2.5.ini',
                 'digest': 'aaebca5e140e0099a757903fc9f194f9e6da388eed22d37bfd1625c80aa25903'},
                {'filename': 'mame4all_2.5/mame',
                 'digest': '6bc23b11fbb9a64096408623d476ad16083ef71c5e7919335e8696036034987d'}]
    decode_all(archive, expected, tmp_path)


@pytest.mark.files
@pytest.mark.skipif(sys.platform.startswith("win") and (ctypes.windll.shell32.IsUserAnAdmin() == 0),
                    reason="Administrator rights is required to make symlink on windows")
def test_extract_symlink(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'symlink.7z'), 'rb'))
    assert sorted(archive.getnames()) == ['lib', 'lib/libabc.so', 'lib/libabc.so.1', 'lib/libabc.so.1.2',
                                          'lib/libabc.so.1.2.3', 'lib64']
    archive.extractall(path=tmp_path)
    archive.close()


@pytest.mark.files
def test_lzma2bcj(tmp_path):
    """Test extract archive compressed with LZMA2 and BCJ methods."""
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'lzma2bcj.7z'), 'rb'))
    assert archive.getnames() == ['5.12.1', '5.12.1/msvc2017_64',
                                  '5.12.1/msvc2017_64/bin', '5.12.1/msvc2017_64/bin/opengl32sw.dll']
    archive.extractall(path=tmp_path)
    archive.close()
    m = hashlib.sha256()
    m.update(tmp_path.joinpath('5.12.1/msvc2017_64/bin/opengl32sw.dll').open('rb').read())
    assert m.digest() == binascii.unhexlify('963641a718f9cae2705d5299eae9b7444e84e72ab3bef96a691510dd05fa1da4')


@pytest.mark.files
def test_extract_lzmabcj_archiveinfo():
    with py7zr.SevenZipFile(os.path.join(testdata_path, 'lzma_bcj.7z'), 'r') as ar:
        ar.archiveinfo()


@pytest.mark.files
@pytest.mark.xfail(reason="Uknown problem that it become no data exception.")
def test_extract_lzmabcj(tmp_path):
    with py7zr.SevenZipFile(os.path.join(testdata_path, 'lzmabcj.7z'), 'r') as ar:
        ar.extractall(path=tmp_path)


@pytest.mark.files
def test_zerosize(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'zerosize.7z'), 'rb'))
    archive.extractall(path=tmp_path)
    archive.close()


@pytest.mark.api
def test_register_unpack_archive(tmp_path):
    shutil.register_unpack_format('7zip', ['.7z'], unpack_7zarchive)
    shutil.unpack_archive(os.path.join(testdata_path, 'test_1.7z'), tmp_path)
    target = tmp_path.joinpath("setup.cfg")
    expected_mode = 33188
    expected_mtime = 1552522033
    if os.name == 'posix':
        assert target.stat().st_mode == expected_mode
    assert target.stat().st_mtime == expected_mtime
    m = hashlib.sha256()
    m.update(target.open('rb').read())
    assert m.digest() == binascii.unhexlify('ff77878e070c4ba52732b0c847b5a055a7c454731939c3217db4a7fb4a1e7240')
    m = hashlib.sha256()
    m.update(tmp_path.joinpath('setup.py').open('rb').read())
    assert m.digest() == binascii.unhexlify('b916eed2a4ee4e48c51a2b51d07d450de0be4dbb83d20e67f6fd166ff7921e49')
    m = hashlib.sha256()
    m.update(tmp_path.joinpath('scripts/py7zr').open('rb').read())
    assert m.digest() == binascii.unhexlify('b0385e71d6a07eb692f5fb9798e9d33aaf87be7dfff936fd2473eab2a593d4fd')


@pytest.mark.files
def test_skip():
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'test_1.7z'), 'rb'))
    for i, cf in enumerate(archive.files):
        assert cf is not None
        archive.worker.register_filelike(cf.id, None)
    archive.worker.extract(archive.fp, parallel=True)
    archive.close()


@pytest.mark.files
def test_github_14_multi(tmp_path):
    """ multiple unnamed objects."""
    archive = py7zr.SevenZipFile(os.path.join(testdata_path, 'github_14_multi.7z'), 'r')
    assert archive.getnames() == ['github_14_multi', 'github_14_multi']
    archive.extractall(path=tmp_path)
    archive.close()
    with tmp_path.joinpath('github_14_multi').open('rb') as f:
        assert f.read() == bytes('Hello GitHub issue #14 1/2.\n', 'ascii')
    with tmp_path.joinpath('github_14_multi_0').open('rb') as f:
        assert f.read() == bytes('Hello GitHub issue #14 2/2.\n', 'ascii')


@pytest.mark.files
def test_multiblock(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'mblock_1.7z'), 'rb'))
    archive.extractall(path=tmp_path)
    archive.close()
    m = hashlib.sha256()
    m.update(tmp_path.joinpath('bin/7zdec.exe').open('rb').read())
    assert m.digest() == binascii.unhexlify('e14d8201c5c0d1049e717a63898a3b1c7ce4054a24871daebaa717da64dcaff5')


@pytest.mark.files
@pytest.mark.skipif(sys.platform.startswith('win'), reason="Cannot unlink opened file on Windows")
def test_multiblock_unlink(tmp_path):
    """When passing opened file object, even after unlink it should work."""
    shutil.copy(os.path.join(testdata_path, 'mblock_1.7z'), str(tmp_path))
    src = tmp_path.joinpath('mblock_1.7z')
    archive = py7zr.SevenZipFile(open(str(src), 'rb'))
    os.unlink(str(src))
    archive.extractall(path=tmp_path)
    archive.close()


@pytest.mark.files
def test_multiblock_zerosize(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'mblock_2.7z'), 'rb'))
    archive.extractall(path=tmp_path)
    archive.close()


@pytest.mark.files
@pytest.mark.timeout(10, method='thread')
def test_multiblock_lzma_bug(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'mblock_3.7z'), 'rb'))
    archive.extractall(path=tmp_path)
    archive.close()
    m = hashlib.sha256()
    m.update(tmp_path.joinpath('5.13.0/mingw73_64/plugins/canbus/qtvirtualcanbusd.dll').open('rb').read())
    assert m.digest() == binascii.unhexlify('98985de41ddba789d039bb10d86ea3015bf0d8d9fa86b25a0490044c247233d3')


@pytest.mark.files
def test_copy(tmp_path):
    """ test loading of copy compressed files.(help wanted)"""
    check_archive(py7zr.SevenZipFile(open(os.path.join(testdata_path, 'copy.7z'), 'rb')), tmp_path)


@pytest.mark.files
def test_close_unlink(tmp_path):
    shutil.copyfile(os.path.join(testdata_path, 'test_1.7z'), str(tmp_path.joinpath('test_1.7z')))
    archive = py7zr.SevenZipFile(tmp_path.joinpath('test_1.7z'))
    archive.extractall(path=tmp_path)
    archive.close()
    tmp_path.joinpath('test_1.7z').unlink()


@pytest.mark.files
@pytest.mark.asyncio
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
@pytest.mark.skipif(hasattr(sys, 'pypy_version_info'), reason="Not working with pypy3")
def test_asyncio_executor(tmp_path):
    shutil.copyfile(os.path.join(testdata_path, 'test_1.7z'), str(tmp_path.joinpath('test_1.7z')))
    loop = asyncio.get_event_loop()
    task = asyncio.ensure_future(aio7zr(tmp_path.joinpath('test_1.7z'), path=tmp_path))
    loop.run_until_complete(task)
    loop.run_until_complete(asyncio.sleep(3))
    os.unlink(str(tmp_path.joinpath('test_1.7z')))


@pytest.mark.files
def test_no_main_streams(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'test_folder.7z'), 'rb'))
    archive.extractall(path=tmp_path)
    archive.close()


@pytest.mark.files
def test_extract_encrypted_1(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'encrypted_1.7z'), 'rb'), password='secret')
    archive.extractall(path=tmp_path)
    archive.close()


@pytest.mark.files
@pytest.mark.timeout(30)
@pytest.mark.skipif(sys.platform.startswith("win") and (ctypes.windll.shell32.IsUserAnAdmin() == 0),
                    reason="Administrator rights is required to make symlink on windows")
def test_extract_encrypted_2(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'encrypted_2.7z'), 'rb'), password='secret')
    archive.extractall(path=tmp_path)
    archive.close()


@pytest.mark.files
def test_extract_bzip2(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'bzip2.7z'), 'rb'))
    archive.extractall(path=tmp_path)
    archive.close()


@pytest.mark.files
def test_extract_bzip2_2(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'bzip2_2.7z'), 'rb'))
    archive.extractall(path=tmp_path)
    archive.close()


@pytest.mark.files
def test_extract_ppmd(tmp_path):
    with pytest.raises(UnsupportedCompressionMethodError):
        archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'ppmd.7z'), 'rb'))
        archive.extractall(path=tmp_path)
        archive.close()


@pytest.mark.files
def test_extract_deflate(tmp_path):
    with py7zr.SevenZipFile(open(os.path.join(testdata_path, 'deflate.7z'), 'rb')) as archive:
        archive.extractall(path=tmp_path)


@pytest.mark.files
@pytest.mark.skipif(sys.platform.startswith("win") and (ctypes.windll.shell32.IsUserAnAdmin() == 0),
                    reason="Administrator rights is required to make symlink on windows")
def test_extract_symlink_with_relative_target_path(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'symlink.7z'), 'rb'))
    os.chdir(str(tmp_path))
    os.makedirs(str(tmp_path.joinpath('target')))  # py35 need str() against pathlib.Path
    archive.extractall(path='target')
    assert os.readlink(str(tmp_path.joinpath('target/lib/libabc.so.1.2'))) == 'libabc.so.1.2.3'
    archive.close()


@pytest.mark.files
@pytest.mark.skipif(sys.platform.startswith("win") and (ctypes.windll.shell32.IsUserAnAdmin() == 0),
                    reason="Administrator rights is required to make symlink on windows")
def test_extract_emptystream_mix(tmp_path):
    archive = py7zr.SevenZipFile(os.path.join(testdata_path, 'test_6.7z'), 'r')
    archive.extractall(path=tmp_path)
    archive.close()

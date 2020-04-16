import binascii
import ctypes
import filecmp
import hashlib
import lzma
import os
import pathlib
import shutil
import stat
import sys
from datetime import datetime

import pytest

import py7zr.archiveinfo
import py7zr.compression
import py7zr.helpers
import py7zr.properties
from py7zr import SevenZipFile, pack_7zarchive
from py7zr.py7zr import FILE_ATTRIBUTE_UNIX_EXTENSION
from py7zr.helpers import readlink

from . import ltime

testdata_path = os.path.join(os.path.dirname(__file__), 'data')


def check_bit(val, mask):
    return val & mask == mask


@pytest.mark.unit
def test_simple_compress_and_decompress():
    sevenzip_compressor = py7zr.compression.SevenZipCompressor()
    lzc = sevenzip_compressor.compressor
    out1 = lzc.compress(b"Some data\n")
    out2 = lzc.compress(b"Another piece of data\n")
    out3 = lzc.compress(b"Even more data\n")
    out4 = lzc.flush()
    result = b"".join([out1, out2, out3, out4])
    size = len(result)
    #
    filters = sevenzip_compressor.filters
    decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
    out5 = decompressor.decompress(result)
    assert out5 == b'Some data\nAnother piece of data\nEven more data\n'
    #
    coders = sevenzip_compressor.coders
    crc = py7zr.helpers.calculate_crc32(result)
    decompressor = py7zr.compression.SevenZipDecompressor(coders, size, crc)
    out6 = decompressor.decompress(result)
    assert out6 == b'Some data\nAnother piece of data\nEven more data\n'


@pytest.mark.basic
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_single_encoded_header(capsys, tmp_path):
    target = tmp_path.joinpath('target.7z')
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(True)
    archive.writeall(os.path.join(testdata_path, "test1.txt"), "test1.txt")
    assert len(archive.files) == 1
    archive.close()
    with target.open('rb') as target_archive:
        val = target_archive.read(1000)
        assert val.startswith(py7zr.properties.MAGIC_7Z)
    archive = py7zr.SevenZipFile(target, 'r')
    assert archive.test()
    archive.close()
    ctime = datetime.utcfromtimestamp(pathlib.Path(os.path.join(testdata_path, "test1.txt")).stat().st_ctime)
    expected = "total 1 files and directories in archive\n" \
               "   Date      Time    Attr         Size   Compressed  Name\n" \
               "------------------- ----- ------------ ------------  ------------------------\n"
    expected += "{} ....A           33           37  test1.txt\n".format(ltime(ctime))
    expected += "------------------- ----- ------------ ------------  ------------------------\n"
    cli = py7zr.cli.Cli()
    cli.run(["l", str(target)])
    out, err = capsys.readouterr()
    assert expected == out


@pytest.mark.basic
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_directory_encoded_header(tmp_path):
    target = tmp_path.joinpath('target.7z')
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(True)
    archive.writeall(os.path.join(testdata_path, "src"), "src")
    assert len(archive.files) == 2
    archive._write_archive()
    assert archive.header.main_streams.packinfo.numstreams == 1
    assert archive.header.main_streams.packinfo.packsizes == [17]
    assert archive.header.main_streams.unpackinfo.numfolders == 1
    assert len(archive.header.main_streams.unpackinfo.folders) == 1
    assert len(archive.header.main_streams.unpackinfo.folders[0].coders) == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numinstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numoutstreams'] == 1
    assert archive.header.main_streams.substreamsinfo.unpacksizes == [11]
    assert len(archive.header.files_info.files) == 2
    archive._fpclose()
    with target.open('rb') as target_archive:
        val = target_archive.read(1000)
        assert val.startswith(py7zr.properties.MAGIC_7Z)
    archive = py7zr.SevenZipFile(target, 'r')
    assert archive.test()


@pytest.mark.files
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_files_encoded_header(tmp_path):
    tmp_path.joinpath('src').mkdir()
    tmp_path.joinpath('tgt').mkdir()
    py7zr.unpack_7zarchive(os.path.join(testdata_path, 'test_1.7z'), path=tmp_path.joinpath('src'))
    target = tmp_path.joinpath('target.7z')
    os.chdir(tmp_path.joinpath('src'))
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(True)
    archive.writeall('.')
    archive._write_archive()
    assert len(archive.files) == 4
    assert len(archive.header.files_info.files) == 4
    expected = [True, False, False, False]
    for i, f in enumerate(archive.header.files_info.files):
        f['emptystream'] = expected[i]
    assert archive.header.files_info.emptyfiles == [True, False, False, False]
    assert archive.header.files_info.files[3]['emptystream'] is False
    expected_attributes = stat.FILE_ATTRIBUTE_ARCHIVE
    if os.name == 'posix':
        expected_attributes |= 0x8000 | (0o644 << 16)
    assert archive.header.files_info.files[3]['attributes'] == expected_attributes
    assert archive.header.files_info.files[3]['maxsize'] == 441
    assert archive.header.files_info.files[3]['uncompressed'] == 559
    assert archive.header.main_streams.packinfo.numstreams == 1
    assert archive.header.main_streams.packinfo.packsizes == [441]
    assert archive.header.main_streams.substreamsinfo.num_unpackstreams_folders == [3]
    assert archive.header.main_streams.substreamsinfo.digestsdefined == [True, True, True]
    assert archive.header.main_streams.substreamsinfo.digests == [3010113243, 3703540999, 2164028094]
    assert archive.header.main_streams.substreamsinfo.unpacksizes == [111, 58, 559]
    assert len(archive.header.main_streams.unpackinfo.folders) == 1
    assert len(archive.header.main_streams.unpackinfo.folders[0].coders) == 1
    assert archive.header.main_streams.unpackinfo.numfolders == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numinstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numoutstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].solid
    assert archive.header.main_streams.unpackinfo.folders[0].bindpairs == []
    assert archive.header.main_streams.unpackinfo.folders[0].solid is True
    assert archive.header.main_streams.unpackinfo.folders[0].totalin == 1
    assert archive.header.main_streams.unpackinfo.folders[0].totalout == 1
    assert archive.header.main_streams.unpackinfo.folders[0].unpacksizes == [728]  # 728 = 111 + 58 + 559
    assert archive.header.main_streams.unpackinfo.folders[0].digestdefined is False
    assert archive.header.main_streams.unpackinfo.folders[0].crc is None
    archive._fpclose()
    reader = py7zr.SevenZipFile(target, 'r')
    reader.extractall(path=tmp_path.joinpath('tgt'))
    reader.close()
    m = hashlib.sha256()
    m.update((tmp_path / 'tgt' / 'setup.py').open('rb').read())
    assert m.digest() == binascii.unhexlify('b916eed2a4ee4e48c51a2b51d07d450de0be4dbb83d20e67f6fd166ff7921e49')
    m = hashlib.sha256()
    m.update((tmp_path / 'tgt' / 'scripts' / 'py7zr').open('rb').read())
    assert m.digest() == binascii.unhexlify('b0385e71d6a07eb692f5fb9798e9d33aaf87be7dfff936fd2473eab2a593d4fd')
    dc = filecmp.dircmp(tmp_path.joinpath('src'), tmp_path.joinpath('tgt'))
    assert dc.diff_files == []


@pytest.mark.basic
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_file_0(capsys, tmp_path):
    target = tmp_path.joinpath('target.7z')
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(False)
    archive.writeall(os.path.join(testdata_path, "test1.txt"), "test1.txt")
    assert len(archive.files) == 1
    archive.close()
    with target.open('rb') as target_archive:
        val = target_archive.read(1000)
        assert val.startswith(py7zr.properties.MAGIC_7Z)
    archive = py7zr.SevenZipFile(target, 'r')
    assert archive.header.main_streams.substreamsinfo.num_unpackstreams_folders[0] == 1
    assert archive.test()
    ctime = datetime.utcfromtimestamp(pathlib.Path(os.path.join(testdata_path, "test1.txt")).stat().st_ctime)
    expected = "total 1 files and directories in archive\n" \
               "   Date      Time    Attr         Size   Compressed  Name\n" \
               "------------------- ----- ------------ ------------  ------------------------\n"
    expected += "{} ....A           33           37  test1.txt\n".format(ltime(ctime))
    expected += "------------------- ----- ------------ ------------  ------------------------\n"
    cli = py7zr.cli.Cli()
    cli.run(["l", str(target)])
    out, err = capsys.readouterr()
    assert expected == out


@pytest.mark.basic
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_directory(tmp_path):
    target = tmp_path.joinpath('target.7z')
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(False)
    archive.writeall(os.path.join(testdata_path, "src"), "src")
    assert len(archive.files) == 2
    archive._write_archive()
    assert archive.header.main_streams.packinfo.numstreams == 1
    assert archive.header.main_streams.packinfo.packsizes == [17]
    assert archive.header.main_streams.unpackinfo.numfolders == 1
    assert len(archive.header.main_streams.unpackinfo.folders) == 1
    assert len(archive.header.main_streams.unpackinfo.folders[0].coders) == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numinstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numoutstreams'] == 1
    assert archive.header.main_streams.substreamsinfo.unpacksizes == [11]
    assert len(archive.header.files_info.files) == 2
    archive._fpclose()
    with target.open('rb') as target_archive:
        val = target_archive.read(1000)
        assert val.startswith(py7zr.properties.MAGIC_7Z)
    archive = py7zr.SevenZipFile(target, 'r')
    assert archive.test()


@pytest.mark.files
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_files_1(tmp_path):
    tmp_path.joinpath('src').mkdir()
    tmp_path.joinpath('tgt').mkdir()
    py7zr.unpack_7zarchive(os.path.join(testdata_path, 'test_1.7z'), path=tmp_path.joinpath('src'))
    target = tmp_path.joinpath('target.7z')
    os.chdir(tmp_path.joinpath('src'))
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(False)
    archive.writeall('.')
    archive._write_archive()
    assert len(archive.files) == 4
    assert len(archive.header.files_info.files) == 4
    expected = [True, False, False, False]
    for i, f in enumerate(archive.header.files_info.files):
        f['emptystream'] = expected[i]
    assert archive.header.files_info.emptyfiles == [True, False, False, False]
    assert archive.header.files_info.files[3]['emptystream'] is False
    expected_attributes = stat.FILE_ATTRIBUTE_ARCHIVE
    if os.name == 'posix':
        expected_attributes |= 0x8000 | (0o644 << 16)
    assert archive.header.files_info.files[3]['attributes'] == expected_attributes
    assert archive.header.files_info.files[3]['maxsize'] == 441
    assert archive.header.files_info.files[3]['uncompressed'] == 559
    assert archive.header.main_streams.packinfo.numstreams == 1
    assert archive.header.main_streams.packinfo.packsizes == [441]
    assert archive.header.main_streams.substreamsinfo.num_unpackstreams_folders == [3]
    assert archive.header.main_streams.substreamsinfo.digestsdefined == [True, True, True]
    assert archive.header.main_streams.substreamsinfo.digests == [3010113243, 3703540999, 2164028094]
    assert archive.header.main_streams.substreamsinfo.unpacksizes == [111, 58, 559]
    assert len(archive.header.main_streams.unpackinfo.folders) == 1
    assert len(archive.header.main_streams.unpackinfo.folders[0].coders) == 1
    assert archive.header.main_streams.unpackinfo.numfolders == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numinstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numoutstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].solid
    assert archive.header.main_streams.unpackinfo.folders[0].bindpairs == []
    assert archive.header.main_streams.unpackinfo.folders[0].solid is True
    assert archive.header.main_streams.unpackinfo.folders[0].totalin == 1
    assert archive.header.main_streams.unpackinfo.folders[0].totalout == 1
    assert archive.header.main_streams.unpackinfo.folders[0].unpacksizes == [728]  # 728 = 111 + 58 + 559
    assert archive.header.main_streams.unpackinfo.folders[0].digestdefined is False
    assert archive.header.main_streams.unpackinfo.folders[0].crc is None
    archive._fpclose()
    # split archive.close() into _write_archive() and _fpclose()
    reader = py7zr.SevenZipFile(target, 'r')
    reader.extractall(path=tmp_path.joinpath('tgt'))
    reader.close()
    m = hashlib.sha256()
    m.update((tmp_path / 'tgt' / 'setup.py').open('rb').read())
    assert m.digest() == binascii.unhexlify('b916eed2a4ee4e48c51a2b51d07d450de0be4dbb83d20e67f6fd166ff7921e49')
    m = hashlib.sha256()
    m.update((tmp_path / 'tgt' / 'scripts' / 'py7zr').open('rb').read())
    assert m.digest() == binascii.unhexlify('b0385e71d6a07eb692f5fb9798e9d33aaf87be7dfff936fd2473eab2a593d4fd')
    dc = filecmp.dircmp(tmp_path.joinpath('src'), tmp_path.joinpath('tgt'))
    assert dc.diff_files == []


@pytest.mark.api
def test_register_archive_format(tmp_path):
    tmp_path.joinpath('src').mkdir()
    tmp_path.joinpath('tgt').mkdir()
    # Prepare test data
    py7zr.unpack_7zarchive(os.path.join(testdata_path, 'test_1.7z'), path=tmp_path.joinpath('src'))
    #
    shutil.register_archive_format('7zip', pack_7zarchive, description='7zip archive')
    shutil.make_archive(str(tmp_path.joinpath('target')), '7zip', str(tmp_path.joinpath('src')))
    # check result
    archive = SevenZipFile(tmp_path.joinpath('target.7z'))
    archive.extractall(path=tmp_path.joinpath('tgt'))
    archive.close()
    m = hashlib.sha256()
    m.update((tmp_path / 'tgt' / 'setup.py').open('rb').read())
    assert m.digest() == binascii.unhexlify('b916eed2a4ee4e48c51a2b51d07d450de0be4dbb83d20e67f6fd166ff7921e49')
    m = hashlib.sha256()
    m.update((tmp_path / 'tgt' / 'scripts' / 'py7zr').open('rb').read())
    assert m.digest() == binascii.unhexlify('b0385e71d6a07eb692f5fb9798e9d33aaf87be7dfff936fd2473eab2a593d4fd')


@pytest.mark.api
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_with_simple_filter(tmp_path):
    my_filters = [{"id": lzma.FILTER_LZMA2, "preset": lzma.PRESET_DEFAULT}, ]
    target = tmp_path.joinpath('target.7z')
    archive = py7zr.SevenZipFile(target, 'w', filters=my_filters)
    archive.writeall(os.path.join(testdata_path, "src"), "src")
    archive.close()


@pytest.mark.api
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_with_custom_filter(tmp_path):
    my_filters = [
        {"id": lzma.FILTER_DELTA, "dist": 5},
        {"id": lzma.FILTER_LZMA2, "preset": 7 | lzma.PRESET_EXTREME},
    ]
    target = tmp_path.joinpath('target.7z')
    archive = py7zr.SevenZipFile(target, 'w', filters=my_filters)
    archive.writeall(os.path.join(testdata_path, "src"), "src")
    archive.close()


@pytest.mark.files
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_files_2(tmp_path):
    tmp_path.joinpath('src').mkdir()
    tmp_path.joinpath('tgt').mkdir()
    py7zr.unpack_7zarchive(os.path.join(testdata_path, 'test_2.7z'), path=tmp_path.joinpath('src'))
    target = tmp_path.joinpath('target.7z')
    os.chdir(tmp_path.joinpath('src'))
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(False)
    archive.writeall('.')
    archive.close()
    reader = py7zr.SevenZipFile(target, 'r')
    reader.extractall(path=tmp_path.joinpath('tgt'))
    reader.close()
    dc = filecmp.dircmp(tmp_path.joinpath('src'), tmp_path.joinpath('tgt'))
    assert dc.diff_files == []


@pytest.mark.files
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
@pytest.mark.skipif(sys.platform.startswith("win") and (ctypes.windll.shell32.IsUserAnAdmin() == 0),
                    reason="Administrator rights is required to make symlink on windows")
def test_compress_files_3(tmp_path):
    tmp_path.joinpath('src').mkdir()
    tmp_path.joinpath('tgt').mkdir()
    py7zr.unpack_7zarchive(os.path.join(testdata_path, 'test_3.7z'), path=tmp_path.joinpath('src'))
    target = tmp_path.joinpath('target.7z')
    os.chdir(tmp_path.joinpath('src'))
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(False)
    archive.writeall('.')
    archive.close()
    reader = py7zr.SevenZipFile(target, 'r')
    reader.extractall(path=tmp_path.joinpath('tgt'))
    reader.close()
    dc = filecmp.dircmp(tmp_path.joinpath('src'), tmp_path.joinpath('tgt'))
    assert dc.diff_files == []


@pytest.mark.files
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
@pytest.mark.skipif(sys.platform.startswith("win") and (ctypes.windll.shell32.IsUserAnAdmin() == 0),
                    reason="Administrator rights is required to make symlink on windows")
def test_compress_symlink(tmp_path):
    tmp_path.joinpath('src').mkdir()
    tmp_path.joinpath('tgt').mkdir()
    py7zr.unpack_7zarchive(os.path.join(testdata_path, 'symlink.7z'), path=tmp_path.joinpath('src'))
    target = tmp_path.joinpath('target.7z')
    os.chdir(tmp_path.joinpath('src'))
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(False)
    archive.writeall('.')
    archive._write_archive()
    assert len(archive.header.files_info.files) == 6
    assert archive.header.main_streams.substreamsinfo.num_unpackstreams_folders == [5]
    assert len(archive.files) == 6
    assert len(archive.header.files_info.files) == 6
    expected = [True, False, False, False, False, False]
    for i, f in enumerate(archive.header.files_info.files):
        f['emptystream'] = expected[i]
    assert archive.header.files_info.files[5]['maxsize'] == 1543
    assert archive.header.main_streams.packinfo.packsizes == [1543]
    assert archive.header.files_info.files[4]['uncompressed'] == 6536
    assert archive.header.files_info.files[1]['filename'] == 'lib/libabc.so'
    assert archive.header.files_info.files[2]['filename'] == 'lib/libabc.so.1'
    if os.name == 'nt':
        assert check_bit(archive.header.files_info.files[2]['attributes'], stat.FILE_ATTRIBUTE_REPARSE_POINT)
    else:
        assert check_bit(archive.header.files_info.files[2]['attributes'], FILE_ATTRIBUTE_UNIX_EXTENSION)
        assert stat.S_ISLNK(archive.header.files_info.files[2]['attributes'] >> 16)
    assert archive.header.main_streams.packinfo.numstreams == 1
    assert archive.header.main_streams.substreamsinfo.digestsdefined == [True, True, True, True, True]
    assert archive.header.main_streams.substreamsinfo.unpacksizes == [11, 13, 15, 6536, 3]
    assert archive.header.main_streams.substreamsinfo.digests == [4262439050, 2607345479,
                                                                  2055456646, 437637236, 2836347852]
    assert archive.header.main_streams.substreamsinfo.num_unpackstreams_folders == [5]
    assert len(archive.header.main_streams.unpackinfo.folders) == 1
    assert len(archive.header.main_streams.unpackinfo.folders[0].coders) == 1
    assert archive.header.main_streams.unpackinfo.numfolders == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numinstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numoutstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].solid
    assert archive.header.main_streams.unpackinfo.folders[0].bindpairs == []
    assert archive.header.main_streams.unpackinfo.folders[0].solid is True
    assert archive.header.main_streams.unpackinfo.folders[0].totalin == 1
    assert archive.header.main_streams.unpackinfo.folders[0].totalout == 1
    assert archive.header.main_streams.unpackinfo.folders[0].unpacksizes == [6578]
    assert archive.header.main_streams.unpackinfo.folders[0].digestdefined is False
    assert archive.header.main_streams.unpackinfo.folders[0].crc is None
    archive._fpclose()
    # split archive.close() into _write_archive() and _fpclose()
    reader = py7zr.SevenZipFile(target, 'r')
    reader.extractall(path=tmp_path.joinpath('tgt'))
    reader.close()


@pytest.mark.files
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_zerofile(tmp_path):
    tmp_path.joinpath('src').mkdir()
    tmp_path.joinpath('tgt').mkdir()
    with tmp_path.joinpath('src', 'f').open(mode='w') as f:
        f.write('')
    target = tmp_path.joinpath('target.7z')
    os.chdir(tmp_path.joinpath('src'))
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(False)
    archive.writeall('.')
    archive._write_archive()
    assert len(archive.header.files_info.files) == 1
    assert archive.header.main_streams.substreamsinfo.num_unpackstreams_folders == [1]
    assert len(archive.files) == 1
    assert len(archive.header.files_info.files) == 1
    expected = [True]
    for i, f in enumerate(archive.header.files_info.files):
        f['emptystream'] = expected[i]
    archive._fpclose()
    # split archive.close() into _write_archive() and _fpclose()
    reader = py7zr.SevenZipFile(target, 'r')
    reader.extractall(path=tmp_path.joinpath('tgt'))
    reader.close()


@pytest.mark.files
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_directories(tmp_path):
    tmp_path.joinpath('src').mkdir()
    tmp_path.joinpath('tgt1').mkdir()
    tmp_path.joinpath('tgt2').mkdir()
    # target files
    tmp_path.joinpath('src', 'dir1').mkdir()
    tmp_path.joinpath('src', 'dir2').mkdir()
    tmp_path.joinpath('src', 'dir3').mkdir()
    tmp_path.joinpath('src', 'dir4').mkdir()
    tmp_path.joinpath('src', 'dir5').mkdir()
    tmp_path.joinpath('src', 'dir6').mkdir()
    tmp_path.joinpath('src', 'dir7').mkdir()
    tmp_path.joinpath('src', 'dir8').mkdir()
    target = tmp_path.joinpath('target.7z')
    os.chdir(tmp_path.joinpath('src'))
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(False)
    archive.writeall('.')
    archive._write_archive()
    for i, f in enumerate(archive.header.files_info.files):
        f['emptystream'] = True
    archive._fpclose()
    # split archive.close() into _write_archive() and _fpclose()
    reader = py7zr.SevenZipFile(target, 'r')
    reader.extractall(path=tmp_path.joinpath('tgt1'))
    reader.close()


@pytest.mark.files
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
@pytest.mark.xfail(reason="Not implemented yet.")
def test_compress_files_with_password(tmp_path):
    target = tmp_path.joinpath('target.7z')
    archive = py7zr.SevenZipFile(target, mode='w', password='secret')


@pytest.mark.files
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
@pytest.mark.skipif(not sys.platform.startswith("win") or (ctypes.windll.shell32.IsUserAnAdmin() == 0),
                    reason="Administrator rights is required to make symlink on windows")
def test_compress_windows_links(tmp_path):
    # test case derived by github issue#112
    parent_path = tmp_path.joinpath('symb')
    target = tmp_path / "symb_2.7z"
    # prepare test data
    l = []
    parent_path.mkdir()
    # 0
    with parent_path.joinpath("Original1.txt").open('w') as f:
        f.write("real Original1.txt")
    l.append('Original1.txt')
    # 1, 2, 3
    s = parent_path / "rel/path/link_to_Original1.txt"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.symlink_to(parent_path / "Original1.txt", False)
    l.append('rel')
    l.append('rel/path')
    l.append('rel/path/link_to_Original1.txt')
    # 4
    s = parent_path / "rel/path/link_to_link_Original1.txt"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.symlink_to(parent_path / "rel/path/link_to_Original1.txt", False)
    l.append('rel/path/link_to_link_Original1.txt')
    # 5
    s = parent_path / "rel/path/link_to_link_to_link_Original1.txt"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.symlink_to(parent_path / "rel/path/link_to_link_Original1.txt", False)
    l.append('rel/path/link_to_link_to_link_Original1.txt')
    # 6
    s = parent_path / "rel/link_to_link_to_link_Original1.txt"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.symlink_to(parent_path / "rel/path/link_to_link_Original1.txt", False)
    l.append('rel/link_to_link_to_link_Original1.txt')
    # 7, 8
    s = parent_path / "a/rel64"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.symlink_to(parent_path / "rel", True)
    l.append('a')
    l.append('a/rel64')
    # 9 create file
    s = parent_path / "lib/Original2.txt"
    s.parent.mkdir(parents=True, exist_ok=True)
    with parent_path.joinpath("lib/Original2.txt").open('w') as f:
        f.write("real Original2.txt")
    l.append('lib/Original2.txt')
    # 10
    s = parent_path / "lib/Original2.[1.2.3].txt"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.symlink_to(parent_path / "lib/Original2.txt", False)
    l.append('lib/Original2.[1.2.3].txt')
    # 11
    s = parent_path / "lib/Original2.[1.2].txt"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.symlink_to(parent_path / "lib/Original2.[1.2.3].txt", False)
    l.append('lib/Original2.[1.2].txt')
    # 12
    s = parent_path / "lib/Original2.[1].txt"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.symlink_to(parent_path / "lib/Original2.[1.2].txt", False)
    l.append('lib/Original2.[1].txt')
    # 13
    s = parent_path / "lib64"
    s.symlink_to(parent_path / "lib", True)
    l.append('lib64')
    # out of tree
    s = pathlib.Path(os.path.join(parent_path.drive, "Original3.txt"))
    s.parent.mkdir(parents=True, exist_ok=True)
    with open(os.path.join(parent_path.drive, "Original3.txt"), 'w') as f:
        f.write("real Original3.txt")
    # 14
    s = parent_path / "Original3.[1].txt"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.symlink_to(os.path.join(parent_path.drive, "Original3.txt"), False)
    l.append('Original3.[1].txt')
    # create archive
    os.chdir(parent_path)
    archive = py7zr.SevenZipFile(target, 'w')
    for f in l:
        archive.write(f)
    archive._write_archive()
    # asserts
    for i, f in enumerate(l):
        assert archive.header.files_info.files[i]['filename'] == f
        if i in [0, 1, 2, 7, 8, 9]:  # skip general files and directories
            continue
        assert check_bit(archive.header.files_info.files[i]['attributes'], stat.FILE_ATTRIBUTE_REPARSE_POINT)
    #
    archive._fpclose()
    # split archive.close() into _write_archive() and _fpclose()
    reader = py7zr.SevenZipFile(target, 'r')
    reader.extractall(path=tmp_path.joinpath('tgt'))
    reader.close()
    assert readlink(str(tmp_path.joinpath('tgt/rel/path/link_to_Original.txt'))) == '../../Original1.txt'
    assert readlink(str(tmp_path.joinpath('tgt/rel/path/link_to_link_to_Original.txt'))) == 'link_to_Original1.txt'

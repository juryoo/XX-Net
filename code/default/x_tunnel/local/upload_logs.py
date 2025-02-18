import os
import time
import io
import json
import zipfile
import operator

import env_info
import utils
from xlog import getLogger, reset_log_files
xlog = getLogger("x_tunnel")

current_path = os.path.dirname(os.path.abspath(__file__))
root_path = os.path.abspath(os.path.join(current_path, os.pardir, os.pardir))
data_path = env_info.data_path
data_xtunnel_path = os.path.join(data_path, 'x_tunnel')
g = None


def sleep(t):
    end_time = time.time() + t
    while g.running:
        if time.time() > end_time:
            return

        sleep_time = min(10, end_time - time.time())
        if sleep_time < 0:
            break

        time.sleep(sleep_time)


def mask_x_tunnel_password(fp):
    with open(fp, "r") as fd:
        dat = json.load(fd)
        del dat["login_password"]
        dat_str = json.dumps(dat)
        return dat_str


def list_files():
    log_files = {}
    other_files = []
    for root, subdirs, files in os.walk(data_path):
        for filename in files:
            src_file = os.path.join(root, filename)

            extension = filename.split(".")[-1]
            if extension in ["json", "txt"]:
                other_files.append(src_file)

            if extension not in ["log",]:
                continue

            mtime = os.path.getmtime(src_file)
            log_files[src_file] = mtime

    # pack new log first, skip old log if size exceed.
    files = sorted(list(log_files.items()), key=operator.itemgetter(1), reverse=True)
    log_files_list = [src_file for src_file, mtime in files]

    # always pack other files(.json and .txt).
    return other_files + log_files_list


def pack_logs(max_size=800 * 1024):
    content_size = 0
    try:
        files = list_files()
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, mode="w") as zfd:
            for src_file in files:
                file_size = os.path.getsize(src_file)
                content_size += file_size
                if content_size > max_size:
                    break

                relate_path = src_file[len(data_path) + 1:]
                # xlog.debug("Add file:%s size:%d", relate_path, file_size)

                if relate_path.endswith("client.json"):
                    content = mask_x_tunnel_password(src_file)
                    zfd.writestr(relate_path, content)
                else:
                    zfd.write(src_file, arcname=relate_path)

                if content_size > max_size:
                    break
        return zip_buffer.getvalue()
    except Exception as e:
        xlog.exception("packing logs except:%r", e)
        return None


def upload_logs_thread():
    global g

    if not g:
        from . import global_var
        g = global_var

    sleep(3 * 60)
    while g.running:
        if not g.running or not g.server_host or not g.session or g.session.last_receive_time == 0:
            time.sleep(10)
        else:
            break

    sleep(30)
    if not g.running:
        return

    session_id = utils.to_str(g.session.session_id)
    data = pack_logs()
    upload(session_id, data)


def upload(session_id, data):
    try:
        content, status, response = g.http_client.request(method="POST", host=g.server_host,
                                                          path="/upload_logs?session_id=%s" % session_id,
                                                          data=data,
                                                          headers={"Content-Length": str(len(data))})

    except Exception as e:
        xlog.exception("upload logs:%r ", e)
        return

    if status != 200:
        xlog.warn("upload logs status:%r ", status)
        return

    # xlog.info("upload logs successful")
    reset_log_files()

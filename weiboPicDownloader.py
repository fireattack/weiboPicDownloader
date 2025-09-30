import argparse
import concurrent.futures
import datetime
import json
import math
import operator
import platform
import re
import random
import sys
import time
from functools import reduce
from pathlib import Path

import dateutil.parser
import requests

if platform.system() == 'Windows':
    if operator.ge(*map(lambda version: list(map(int, version.split('.'))), [platform.version(), '10.0.14393'])):
        pass
    else:
        import colorama
        colorama.init()

try:
    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
except:
    pass

parser = argparse.ArgumentParser(prog='weiboPicDownloader')
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument('-u', metavar='user', dest='users', nargs='+', help='specify nickname or id of weibo users')
group.add_argument('-f', metavar='file', dest='files', nargs='+', help='import list of users from files')
parser.add_argument('-d', metavar='directory', dest='directory', help='set picture saving path')
parser.add_argument('-s', metavar='size', dest='size', default=20, type=int, help='set size of thread pool')
parser.add_argument('-r', metavar='retry', dest='retry', default=10, type=int, help='set maximum number of retries')
parser.add_argument('-i', metavar='interval', dest='interval', default=1, type=float, help='set interval for feed requests')
parser.add_argument('-c', metavar='cookie', dest='cookie', help='set cookie if needed')
parser.add_argument('-b', metavar='boundary', dest='boundary', default=':', help='focus on weibos in the id range')
parser.add_argument('-R', metavar='resource', dest='resource', help='use dumped resource')
parser.add_argument('-n', metavar='name', dest='name', default='{name}',    help='customize naming format')
parser.add_argument('-v', dest='video', action='store_true', help='download videos together')
parser.add_argument('-o', dest='overwrite', action='store_true', help='overwrite existing files')


UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
session_anonymous = requests.Session()
session_weibo_cn = None
session_weibo_com = None


def initialize_visitor_session():
    global session_weibo_cn

    print('[Info] Initialize a visitor session for weibo.cn for API endpoints.')
    session_weibo_cn = requests.Session()
    DATA = {
        'cb': 'visitor_gray_callback',
        'tid': '',
        'from': 'weibo'
    }
    r = session_weibo_cn.post('https://visitor.passport.weibo.cn/visitor/genvisitor2', data=DATA)
    match = re.search(r'visitor_gray_callback\((\{.*\})\);', r.text)
    if match:
        visitor_data = match.group(1)
        visitor_data = json.loads(visitor_data).get('data', {})
    else:
        print(f'[Error] Failed to get visitor data: {r.text}')
        raise ValueError('Failed to get visitor data.')

    sub = visitor_data.get('sub')
    subp = visitor_data.get('subp')

    if sub and subp:
        session_weibo_cn.cookies.set('SUB', sub, domain='.weibo.cn')
        session_weibo_cn.cookies.set('SUBP', subp, domain='.weibo.cn')
    else:
        raise Exception('[Error] Failed to get visitor cookies.')

def initialize_weibo_com_session():
    # Ref:
    # https://github.com/yt-dlp/yt-dlp/blob/d925e92b710153d0d51d030f115b3c87226bc0f0/yt_dlp/extractor/weibo.py#L24
    global session_weibo_com

    print('[Info] Initialize a visitor session for weibo.com for HD (>720p) video.')
    session_weibo_com = requests.Session()
    session_weibo_com.headers.update({"User-Agent": UA})
    r = session_weibo_com.post(
        'https://passport.weibo.com/visitor/genvisitor',
        data={
            'cb': 'gen_callback',
            'fp': '{"os":"1","browser":"Chrome140,0,0,0","fonts":"undefined","screenInfo":"1920*1080*24","plugins":""}'
        }
    )
    # 'window.gen_callback && gen_callback({"retcode":20000000,"msg":"succ","data":{"tid":"01AVnbdu31T2260cpRnxmRjpH48iI64qeux7YqiGnXZ1xJ","new_tid":false,"confidence":90}});'
    match = re.search(r'gen_callback\((\{.*\})\);', r.text)
    if match:
        visitor_data = match.group(1)
        visitor_data = json.loads(visitor_data).get('data', {})
    else:
        print(f'[Error] Failed to get visitor data: {r.text}')
        raise ValueError('Failed to get visitor data.')

    tid = visitor_data.get('tid', '')
    new_tid = visitor_data.get('new_tid', False)
    confidence = visitor_data.get('confidence', 100)
    session_weibo_com.get(
        'https://passport.weibo.com/visitor/visitor',
        params={
            'a': 'incarnate',
            't': tid,
            'w': 3 if new_tid else 2,
            'c': f'{confidence:03d}',
            'gc': '',
            'cb': 'cross_domain',
            'from': 'weibo',
            '_rand': random.random(),
        }
    )

def nargs_fit(parser, args):
    flags = parser._option_string_actions
    short_flags = [flag for flag in flags.keys() if len(flag) == 2]
    long_flags = [flag for flag in flags.keys() if len(flag) > 2]
    short_flags_with_nargs = set([flag[1] for flag in short_flags if flags[flag].nargs])
    short_flags_without_args = set([flag[1] for flag in short_flags if flags[flag].nargs == 0])
    validate = lambda part : (re.match(r'-[^-]', part) and (set(part[1:-1]).issubset(short_flags_without_args) and '-' + part[-1] in short_flags)) or (part.startswith('--') and part in long_flags)

    greedy = False
    for index, arg in enumerate(args):
        if arg.startswith('-'):
            valid = validate(arg)
            if valid and arg[-1] in short_flags_with_nargs:
                greedy = True
            elif valid:
                greedy = False
            elif greedy:
                args[index] = ' ' + args[index]
    return args

class Printer():
    def __init__(self):
        self.pinned = False

    def print_fit(self, string, pin=False, *args, **kwargs):
        if pin == True:
            if self.pinned:
                print(f'\r\033[K{string}', end='')
            else:
                print(string, end='')
            self.pinned = True
        else:
            if self.pinned:
                print()
            print(string, *args, **kwargs)
            self.pinned = False

print_fit = Printer().print_fit

def merge(*dicts):
    result = {}
    for dictionary in dicts:
        result.update(dictionary)
    return result

def quit(string = ''):
    print_fit(string)
    exit()

def confirm(message):
    while True:
        answer = input(f'{message} [Y/n] ').strip()
        if answer == 'y' or answer == 'Y':
            return True
        elif answer == 'n' or answer == 'N':
            return False
        print_fit('unexpected answer')

def progress(part, whole, percent=False):
    if percent:
        return f'{part}/{whole}({int(float(part) / whole * 100)}%)'
    else:
        return f'{part}/{whole}'

def read_from_file(path):
    try:
        with open(path, 'r') as f:
            return [line.strip() for line in f]
    except Exception as e:
        quit(str(e))

def nickname_to_uid(nickname):
    # TODO: check if this API can be still accessed
    url = f'https://m.weibo.cn/n/{nickname}'
    response = session_anonymous.get(url)
    if re.search(r'/u/\d{10}$', response.url):
        return response.url[-10:]
    else:
        return

def uid_to_nickname(uid):
    url = f'https://m.weibo.cn/api/container/getIndex?type=uid&value={uid}'
    response = session_weibo_cn.get(url, timeout=10)
    try:
        return json.loads(response.text)['data']['userInfo']['screen_name']
    except:
        return

def bid_to_mid(string):
    alphabet = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    alphabet = {x: n for n, x in enumerate(alphabet)}

    splited = [string[(g + 1) * -4 : g * -4 if g * -4 else None] for g in reversed(range(math.ceil(len(string) / 4.0)))]
    convert = lambda s : str(sum([alphabet[c] * (len(alphabet) ** k) for k, c in enumerate(reversed(s))])).zfill(7)
    return int(''.join(map(convert, splited)))

def parse_date(text):
    now = datetime.datetime.now()
    if '前' in text:
        if '小时' in text:
            return (now - datetime.timedelta(hours = int(re.search(r'\d+', text).group()))).date()
        else:
            return now.date()
    if '昨天' in text:
        return now.date() - datetime.timedelta(days = 1)

    # It's now in format of 'Sat Aug 01 00:59:22 +0800 2020' so a simple dateutil.parser is enough.
    try:
        my_time = dateutil.parser.parse(text)
        return my_time.date()
    except:
        pass
    if re.search(r'^[\d|-]+$', text):
        return datetime.datetime.strptime(((str(now.year) + '-') if not re.search(r'^\d{4}', text) else '') + text, '%Y-%m-%d').date()

def compare(standard, operation, candidate):
    for target in candidate:
        try:
            result = '>=<'
            if standard > target: result = '>'
            elif standard == target: result = '='
            else: result = '<'
            return result in operation
        except TypeError:
            pass

def get_hd_video(bid):
    if session_weibo_com is None:
        initialize_weibo_com_session()

    url = f'https://weibo.com/ajax/statuses/show?id={bid}' # mid also works
    print_fit(f'[Info] Try to get higher quality video from {url} ...', end='')
    with session_weibo_com.get(url, headers={'Referer': 'https://weibo.com/'}, timeout=10) as r:
        ajax_data = r.json()
        videos = [(
            playback['play_info']["width"],
            playback['play_info']["height"],
            playback['play_info']["bitrate"],
            playback['play_info']["url"]
        ) for playback in ajax_data["page_info"]["media_info"]["playback_list"]
            if playback['play_info']["mime"] == "video/mp4" # filter out thumbnails
        ]
        if videos:
            videos.sort(reverse=True)
            best = videos[0]
            video_url = best[3]
            print_fit(f' best video: {best[0]}x{best[1]}, {best[2]/1024:.0f}kbps')
            return video_url

def get_resources(uid, video, interval, limit):
    page = 1
    size = 25
    amount = 0
    total = 0
    empty = 0
    aware = 1
    exceed = False
    resources = []

    info = dict()

    while empty < aware and not exceed:
        try:
            url = f'https://m.weibo.cn/api/container/getIndex?count={size}&page={page}&containerid=107603{uid}'
            response = session_weibo_cn.get(url, timeout=10)
            assert response.status_code != 418
            json_data = json.loads(response.text)
        except AssertionError:
            print_fit(f'punished by anti-scraping mechanism (#{page})', pin=True)
            empty = aware
        except Exception as ex:
            print_fit(f'[Error] {ex}', pin=True)
        else:
            empty = empty + 1 if json_data['ok'] == 0 else 0
            if total == 0 and 'cardlistInfo' in json_data['data']: total = json_data['data']['cardlistInfo']['total']
            cards = json_data['data']['cards']
            for card in cards:
                if 'mblog' in card:
                    mblog = card['mblog']
                    # We check if a post is sticky. Sticky post will NOT be used to when see if we have reached the limit or not;
                    # but will still be processed if within the interval.
                    is_top = False
                    if mblog.get('isTop', False):
                        is_top = True
                    if mblog.get('mblogtype', None) == 2:
                        is_top = True

                    mid = int(mblog['mid'])
                    bid = mblog['bid']
                    date = parse_date(mblog['created_at'])
                    if 'raw_text' in mblog:
                        text = mblog['raw_text']
                    else:
                        text = mblog['text']
                    mark = {'uid': uid, 'mid': mid, 'bid': bid, 'date': date, 'text': text}
                    # Try to get username again
                    if 'screen_name' not in info and str(mblog['user']['id']) == uid:
                        info['screen_name'] = mblog['user']['screen_name']
                    if not is_top and 'newest_bid' not in info: #Save newest bid
                        info['newest_bid'] = bid

                    if not is_top and compare(limit[0], '>=', [mid, date]): exceed = True
                    if compare(limit[0], '>=', [mid, date]) or compare(limit[1], '<', [mid, date]): continue
                    amount += 1 # only count if not skipped
                    blog_url = card['scheme']
                    weibo_cn_url = f'https://m.weibo.cn/statuses/show?id={bid}'

                    if 'pics' in mblog:
                        if mblog['pic_num'] > 9:  # More than 9 images
                            print_fit(f'[Info] Find more than 9 pictures for {blog_url} ...', end='')
                            with session_weibo_cn.get(weibo_cn_url, headers={'User-Agent': UA, 'referer': blog_url}, timeout=10) as r:
                                pics = r.json()["data"]["pics"]
                                print_fit(f' got {len(pics)} pictures.')
                        else:
                            pics = mblog['pics']
                        for index, pic in enumerate(pics, 1):
                            if 'large' in pic:
                                resources.append(merge({'url': pic['large']['url'], 'index': index, 'type': 'photo'}, mark))
                    elif video and 'page_info' in mblog and mblog['page_info'].get('type', '') == 'video':
                        video_url = None
                        try:
                            video_url = get_hd_video(bid)
                        except Exception as e:
                            print_fit(f'[Warning] failed to get higher quality video: {e}')
                        # if failed, try to get video from the original API endpoint, which only has up to 720p
                        if not video_url:
                            keys = ["mp4_720p_mp4", "stream_url_hd", "mp4_hd_mp4", "stream_url", "mp4_ld_mp4"]
                            media_info = mblog["page_info"].get("media_info", {})
                            urls = mblog["page_info"].get("urls", {})
                            combined = {**media_info, **urls}
                            for key in keys:
                                if key in combined:
                                    video_url = combined[key]
                                    break
                        if video_url:
                            resources.append(merge({'url': video_url, 'index': 1, 'type': 'video'}, mark))
                        else:
                            print_fit(f'[Error] Cannot get video url for {bid}')

            print_fit(f"{'Analysing weibos...' if empty < aware and not exceed else 'Finish analysis'} {progress(amount, total)}(#{page})", pin=True)
            page += 1
        finally:
            time.sleep(interval)

    print_fit(f'Scanned {amount} weibos, get {len(resources)} {"resources" if video else "pictures"}')

    info['weibos_scanned'] = amount
    info['resources_found'] = len(resources)
    return resources, info

def safeify(s):
    template = {'\\': '＼', '/': '／', ':': '：', '*': '＊', '?': '？', '"': '＂', '<': '＜', '>': '＞', '|': '｜', '\r': '', '\n': ''}
    for illegal in template:
        s = s.replace(illegal, template[illegal])
    return s

def format_name(item, template):
    item['name'] = re.sub(r'\?\S+$', '', re.sub(r'^\S+/', '', item['url']))

    def substitute(matched):
        key = matched.group(1).split(':')
        if key[0] not in item:
            return ':'.join(key)
        elif key[0] == 'date':
            return item[key[0]].strftime(key[1]) if len(key) > 1 else str(item[key[0]])
        elif key[0] == 'index':
            return str(item[key[0]]).zfill(int(key[1] if len(key) > 1 else '0'))
        elif key[0] == 'text':
            value = item[key[0]]
            value = value.replace('<br />', ' ') # Replace newline with space
            value = re.sub(r'</*(img|span|a).*?>', '', value) # Remove other HTML tags.
            value = value.replace('無断転載禁止', '')
            value = value.replace('\u200b', '')
            value = value.replace('&amp;', '&')
            value = value.replace('&quot;', '＂')
            value = re.sub(r'#(.+?)(\[?超话\]?)?#', r' \1 ', value)
            value = re.sub(r'\s+', ' ', value)
            value = value.strip()[:100]
            return value
        else:
            return str(item[key[0]])

    return safeify(re.sub(r'{(.*?)}', substitute, template))

def download(url, path, overwrite):
    path = Path(path)
    if path.exists() and not overwrite:
        return True
    try:
        with session_anonymous.get(url, stream=True, timeout=10) as response:
            expected_size = int(response.headers['Content-length'])
            assert expected_size > 0 and response.status_code == 200
            with open(path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        size = path.stat().st_size
        if size != expected_size:
            raise Exception(f'{path.name.split(" ")[-1]}: filesize doesn\'t match header ({expected_size} -> {size}). Re-download...')

        # If the image is directed to something like default_d_h_large.gif,
        # it means the image is "harmonized" and we rename it to .missing to indicate that.
        if response.url != url:
            print_fit(f'[Warning] {url} got redirected to {response.url}. Likely the image is "harmonized".')
            path_temp = path.with_name(path.stem + '.missing' + path.suffix)
            path = path.rename(path_temp)
    except Exception as ex:
        print_fit(ex)
        # remove partially downloaded file if any
        if path.exists():
            path.unlink()
        return False
    else:
        return True

def main(*paras):
    if paras:
        paras = list(map(str, paras))
    else:
        paras = sys.argv[1:]
    paras = nargs_fit(parser, paras)
    if not paras:
        paras = ['-h']
    args = parser.parse_args(paras)

    if args.users:
        users = args.users
    elif args.files:
        users = [read_from_file(path.strip()) for path in args.files]
        users = reduce(lambda x, y : x + y, users)
    users = [user.strip() for user in users]

    if args.directory:
        base = Path(args.directory)
        if base.exists():
            if not base.is_dir(): quit('Saving path is not a directory')
        elif confirm(f'Directory "{base}" doesn\'t exist, help to create?'):
            base.mkdir()
        else:
            quit('Do it youself :)')
    else:
        base = Path(__file__).parent / 'weiboPic'
        base.mkdir(exist_ok=True)

    boundary = args.boundary.split(':')
    boundary = boundary * 2 if len(boundary) == 1 else boundary
    numberify = lambda x: int(x) if re.search(r'^\d+$', x) else bid_to_mid(x)
    dateify = lambda t: datetime.datetime.strptime(t, '@%Y%m%d').date()
    parse_point = lambda p: dateify(p) if p.startswith('@') else numberify(p)
    try:
        boundary[0] = 0 if boundary[0] == '' else parse_point(boundary[0])
        boundary[1] = float('inf') if boundary[1] == '' else parse_point(boundary[1])
        if boundary[0] == boundary[1]:
            if type(boundary[0]) == int:
                boundary[0] = boundary[0] - 1
            else:
                boundary[0] = boundary[0] - datetime.timedelta(days = 1)
        if type(boundary[0]) == type(boundary[1]): assert boundary[0] <= boundary[1]
    except:
        quit(f'invalid id range {args.boundary}')

    if args.cookie:
        session_anonymous.cookies.update({'SUB': args.cookie})
    pool = concurrent.futures.ThreadPoolExecutor(max_workers = args.size)

    initialize_visitor_session()
    results = []

    for number, user in enumerate(users, 1):

        print_fit(f'{number}/{len(users)} {time.ctime()}')

        if re.search(r'^\d{10}$', user):
            nickname = uid_to_nickname(user)
            uid = user
        else:
            nickname = user
            uid = nickname_to_uid(user)

        if not uid:
            print_fit(f'Invalid account {user}')
            print_fit('-' * 30)
            continue

        if not nickname:
            nickname = f'({uid})'

        print_fit(f'{nickname} {uid}')

        if args.resource:
            with open(args.resource, 'r', encoding='utf-8') as f:
                resources = json.load(f)
        else:
            try:
                resources, info = get_resources(uid, args.video, args.interval, boundary)
            except KeyboardInterrupt:
                quit()
        result = {
            'uid': uid,
            'nickname': nickname,
            'newest_bid': ''
        }
        # Rename screen_name to nickname for compatibility.
        if info.get('screen_name', None):
            info['nickname'] = info['screen_name']
            del info['screen_name']

        result.update(info)

        album = base / safeify(result['nickname'])
        if resources and not album.exists(): album.mkdir()
        retry = 0
        while resources and retry <= args.retry:

            if retry > 0:
                print_fit(f'Automatic retry {retry}')
            total = len(resources)
            tasks = []
            done = 0
            failed = {}
            cancel = False

            for resource in resources:
                path = album / format_name(resource, args.name)
                tasks.append(pool.submit(download, resource['url'], path, args.overwrite))

            while done != total:
                try:
                    done = 0
                    for index, task in enumerate(tasks):
                        if task.done() == True:
                            done += 1
                            if task.cancelled(): continue
                            if task.result() == False: failed[index] = ''
                        elif cancel:
                            if not task.cancelled(): task.cancel()
                    time.sleep(0.5)
                except KeyboardInterrupt:
                    cancel = True
                finally:
                    if not cancel:
                        print_fit(
                            f"{'Downloading...' if done != total else 'All tasks done'} {progress(done, total, True)}",
                            pin=True
                        )
                    else:
                        print_fit(f'waiting for cancellation... ({total - done})', pin=True)

            if cancel: quit()
            print_fit(f'Success {total - len(failed)}, failure {len(failed)}, total {total}')

            resources = [resources[index] for index in failed]
            retry += 1

        for resource in resources: print_fit(f'{resource["url"]} {format_name(resource, args.name)} failed')
        print_fit('-' * 30)
        results.append(result)
    print_fit('Done!')
    return results


if __name__ == "__main__":
    main()
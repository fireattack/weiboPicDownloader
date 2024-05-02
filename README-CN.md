# weiboPicDownloader (fork) ![](https://img.shields.io/badge/python-3.8+-blue.svg)

**[English README](README.md)**

**微博媒体批量下载器**

从 https://github.com/nondanee/weiboPicDownloader 分叉而来

主要改进：

* 现在可以下载超过 9 张图片的帖子。
* 现在可以下载高清视频。
* 在使用名称模板时清理来自微博文本内容的文本。
* 重构为模块，更容易整合到其他 Python 脚本/项目中。现在返回一个 dict，以显示下载会话中的一些统计数据。
* 各种 bug 修复。

Breaking 变更：

* 放弃对 Python 2 的支持（只在 3.8 上测试，但应该也适用于更早的一些版本）
* -b（边界）现在在左侧（较早的日期）不包含在内。这是为了便于更新（因此你可以使用 -b last_checked_bid: 只下载新的帖子而不会有重复下载的情况）。使用特定 mid/bid（而不是范围）的 -b 仍然只会下载该特定单个帖子。

## 致谢

* [nondanee/weiboPicDownloader](https://github.com/nondanee/weiboPicDownloader) (停止维护的原版)
  * 根源自 Java 项目 [yAnXImIN/weiboPicDownloader](https://github.com/yAnXImIN/weiboPicDownloader)
  * 也从另一移植项目学到了好多 [ningshu/weiboPicDownloader](https://github.com/ningshu/weiboPicDownloader)

微博免登录接口相关信息可以参考原 repo 的 [wiki](https://github.com/nondanee/weiboPicDownloader/wiki)

## 依赖

```
$ pip install requests
$ pip install colorama # 仅 Windows 10.0.14393 以下需要
```

## 使用

```
$ python .\weiboPicDownloader.py -h
usage: weiboPicDownloader [-h] (-u user [user ...] | -f file [file ...])
                          [-d directory] [-s size] [-r retry] [-i interval]
                          [-c cookie] [-b boundary] [-n name] [-v] [-o]

optional arguments:
  -h, --help          show this help message and exit
  -u user [user ...]  specify nickname or id of weibo users
  -f file [file ...]  import list of users from files
  -d directory        set picture saving path
  -s size             set size of thread pool
  -r retry            set maximum number of retries
  -i interval         set interval for feed requests
  -c cookie           set cookie if needed
  -b boundary         focus on weibos in the id range
  -n name             customize naming format
  -v                  download videos together
  -o                  overwrite existing files
```

必需参数（任选一）

- `-u user` 用户（昵称或 id）
- `-f file` 用户列表文件（昵称或 id，一个用户占一行）

可选参数

- `-d directory` 图片保存路径（默认值：`./weiboPic`）
- `-s size` 线程池大小（默认值：`20`）
- `-r retry` 最大重试次数（默认值：`2`）
- `-i interval` 请求间隔（默认值：`1`，单位：秒）
- `-c cookie` 登录凭据 (需要 cookie 中的 `SUB` 值)
- `-b boundary` 微博 mid/bid 或日期范围（格式：`id:id` 两者之间，`:id` 之前，`id:` 之后，`id` 指定，`:` 全部）。日期使用 `@%Y%m%d`（如 `@20220520`）；否则整数会被视为 mid
- `-n name` 命名模板 (标识符: `url`、`index`、`type`、`mid`、`bid`、`date`、`text`、`name`，`uid` 类似 ["f-Strings"](https://www.python.org/dev/peps/pep-0498/#abstract) 语法)
- `-v` 同时下载秒拍视频
- `-o` 重新下载已保存的文件（默认跳过）

## 如何从浏览器中取得 `SUB` 的值（以 Chrome 举例）

1. 转到 https://m.weibo.cn 并登录
2. 右键检查 > Application > Cookies > https://m.weibo.cn
3. 双击 `SUB` 所在行并右键拷贝它的值
4. 将 `SUB` 的值粘贴到命令行窗口，以 `-c <value>` 的方式运行程序
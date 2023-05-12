import argparse
from datetime import date, datetime
import csv
import hashlib
import logging
import re
import time
import feedparser
from bs4 import BeautifulSoup
from http.cookies import SimpleCookie
from notion_client import Client
import requests
from requests.utils import cookiejar_from_dict
import requests


def parse_cookie_string(cookie_string):
    cookie = SimpleCookie()
    cookie.load(cookie_string)
    cookies_dict = {}
    cookiejar = None
    for key, morsel in cookie.items():
        cookies_dict[key] = morsel.value
        cookiejar = cookiejar_from_dict(
            cookies_dict, cookiejar=None, overwrite=True
        )
    return cookiejar


WEREAD_READ_INFO_URL = "https://i.weread.qq.com/book/readinfo"
headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36'}

WEREAD_BASE_URL = "https://weread.qq.com/"
rating_dict = {
    '很差': '⭐️',
    '较差': '⭐️⭐️',
    '还行': '⭐️⭐️⭐️',
    '推荐': '⭐️⭐️⭐️⭐️',
    '力荐': '⭐️⭐️⭐️⭐️⭐️',
}
rating_dict2 = {
    '': '⭐️',
    '1': '⭐️',
    '2': '⭐️⭐️',
    '3': '⭐️⭐️⭐️',
    '4': '⭐️⭐️⭐️⭐️',
    '5': '⭐️⭐️⭐️⭐️⭐️',
}

def feed_parser():
    d = feedparser.parse(url)
    for entry in d.entries:
        print(entry['title'])
        title = entry['title']
        pattern = r'想看|在看|看过|想读|最近在读|读过'
        status = ""
        m = re.match(pattern, title)
        if m:
            status = m.group(0)
            if(status == '最近在读'):
                status = status[2:]
        link = entry['link']
        if 'https' not in link:
            link = link.replace('http','https')
        rating = ''
        note = ''
        date = datetime(*entry.published_parsed[:6])
        soup = BeautifulSoup(entry['description'],features="html.parser")
        
        for p in soup.find_all('p'):
            if '推荐: ' in p.string:
                rating = rating_dict[p.string.split(": ")[1]]
            if '备注: ' in p.string:
                note = p.string.split(": ")[1]
        if ('看' in status):
            parse_movie(date, rating, note, status, link)
        elif ('读' in status):
            parse_book(date, rating, note, status, link)

def parse_movie_csv():
    with open('./data/db-movie-20220918.csv', newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            title = row['\ufeff标题']
            print(title)
            status='看过'
            date = datetime.strptime(row['打分日期'],'%Y/%m/%d')
            print(date)
            rating = rating_dict2[row['个人评分']]
            note = row['我的短评']
            link =row['条目链接'].strip()
            time.sleep(2)
            parse_movie(date, rating, note, status, link)


def parse_movie(date, rating, note, status, link):
    f = {"property": "URL", "url": {"equals": link}}
    response = client.databases.query(
        database_id=database_id, filter=f)
    if (len(response['results']) > 0):
        update(date, rating, note, status,response['results'][0]['id'])
        return
    response = requests.get(link, headers=headers)
    soup = BeautifulSoup(response.content)
    title = soup.find(property='v:itemreviewed').string
    year = soup.find('span', {'class': 'year'}).string[1:-1]
    info = soup.find(id='info')
    # print('info ',info)
    cover = soup.find(id='mainpic').img['src']
    # 导演
    directors = list(filter(lambda x: '/' not in x,info.find('span', {'class': 'attrs'}).strings))
    # 演员
    actors = list()
    actor_span=info.find('span', {'class': 'actor'})
    if actor_span!=None:
        actors = list(map(lambda x: x.string,actor_span.find_all('a')))
    # 类型
    genre = list(map(lambda x: x.string, info.find_all(property='v:genre')))
    country = ''
    imdb = ''
    for span in info.find_all('span', {'class': 'pl'}):
        if ('制片国家/地区:' == span.string):
            country = span.next_sibling.string
        if ('IMDb:' == span.string):
            imdb = 'https://www.imdb.com/title/'+span.next_sibling.string.strip()
    insert_movie(title, date, link, cover, rating, note, status,
                 year, directors, actors, genre, country, imdb)


def parse_book(date, rating, note, status, link):
    response = requests.get(link, headers=headers)
    soup = BeautifulSoup(response.content)
    title = soup.find(property='v:itemreviewed').string
    info = soup.find(id='info')
    info = list(map(lambda x: x.replace(':', '').strip(), list(
        filter(lambda x: '\n' not in x, info.strings))))
    dict = {}
    dict['作者']=info[info.index('作者')+1:info.index('出版社')]
    dict['出版年']=info[info.index('出版年')+1:info.index('出版年')+2]
    dict['ISBN']=info[info.index('ISBN')+1:]
    cover = soup.find(id='mainpic').img['src']
    weread = search_book(title)
    if(weread==None):
        f = {"property": "URL", "url": {"equals": link}}
        response = client.databases.query(
        database_id=database_id, filter=f)
        if (len(response['results']) > 0):
            update(date, rating, note, status,response['results'][0]['id'])
            return
        insert_douban_book(title, date, link, cover, dict, rating, note, status)
    else:
        if(not check(weread["bookId"])):
            insert_weread_book(weread)


def transform_id(book_id):
    id_length = len(book_id)

    if re.match("^\d*$", book_id):
        ary = []
        for i in range(0, id_length, 9):
            ary.append(format(int(book_id[i:min(i + 9, id_length)]), 'x'))
        return '3', ary

    result = ''
    for i in range(id_length):
        result += format(ord(book_id[i]), 'x')
    return '4', [result]

def calculate_book_str_id(book_id):
    md5 = hashlib.md5()
    md5.update(book_id.encode('utf-8'))
    digest = md5.hexdigest()
    result = digest[0:3]
    code, transformed_ids = transform_id(book_id)
    result += code + '2' + digest[-2:]

    for i in range(len(transformed_ids)):
        hex_length_str = format(len(transformed_ids[i]), 'x')
        if len(hex_length_str) == 1:
            hex_length_str = '0' + hex_length_str

        result += hex_length_str + transformed_ids[i]

        if i < len(transformed_ids) - 1:
            result += 'g'

    if len(result) < 20:
        result += digest[0:20 - len(result)]

    md5 = hashlib.md5()
    md5.update(result.encode('utf-8'))
    result += md5.hexdigest()[0:3]
    return result


def check(bookId):
    """检查是否已经插入过 如果已经插入了就删除"""
    time.sleep(0.3)
    filter = {
        "property": "Id",
        "rich_text": {
            "equals": bookId
        }
    }
    response = client.databases.query(database_id=database_id, filter=filter)
    return len(response['results']) > 0


def get_read_info(bookId):
    params = dict(bookId=bookId, readingDetail=1,
                  readingBookIndex=1, finishedDate=1)
    r = session.get(WEREAD_READ_INFO_URL, params=params)
    if r.ok:
        return r.json()
    return None


def insert_weread_book(weread):
    """插入到notion"""
    time.sleep(0.3)
    parent = {
        "database_id": database_id,
        "type": "database_id"
    }
    bookId = weread['bookId']
    cover = weread['cover']
    properties = {
        "Name": {"title": [{"type": "text", "text": {"content": weread['title']}}]},
        "Id": {"rich_text": [{"type": "text", "text": {"content":bookId}}]},
        "URL": {"url": f"https://weread.qq.com/web/reader/{calculate_book_str_id(bookId)}"},
        "Author": {"multi_select": [{"name": weread['author']}]},
        "类型": {"status": {"name": "书籍"}},
        "附件": {"files": [{"type": "external", "name": "Cover", "external": {"url": cover}}]},
    }
    read_info = get_read_info(bookId=bookId)
    if read_info != None:
        markedStatus = read_info.get("markedStatus", 0)
        readingTime = read_info.get("readingTime", 0)
        format_time = ""
        hour = readingTime // 3600
        if hour > 0:
            format_time += f"{hour}时"
        minutes = readingTime % 3600 // 60
        if minutes > 0:
            format_time += f"{minutes}分"
        properties["状态"] = {"status": {
            "name": "读过" if markedStatus == 4 else "在读"}}
        properties["ReadingTime"] = {"rich_text": [
            {"type": "text", "text": {"content": format_time}}]}
        if "finishedDate" in read_info:
            properties["读完日期"] = {"date": {"start": datetime.utcfromtimestamp(read_info.get(
                "finishedDate")).strftime("%Y-%m-%d %H:%M:%S"), "time_zone": "Asia/Shanghai"}}

    icon = {
        "type": "external",
        "external": {
            "url": cover
        }
    }
    # notion api 限制100个block
    response = client.pages.create(
        parent=parent, icon=icon, properties=properties)
    id = response["id"]
    return id

def search_book(keyword):
    """搜索书籍"""
    session.get(WEREAD_BASE_URL)
    result = None
    url = "https://i.weread.qq.com/store/search"
    params = {"count":10,"keyword": keyword}
    r = session.get(url, params=params)
    books = r.json().get("books")
    if(len(books) > 0):
        book = books[0]
        bookId = book["bookInfo"]["bookId"]
        result = get_bookinfo(bookId=bookId)
    return result



def get_bookinfo(bookId):
    """获取书的详情"""
    url = "https://i.weread.qq.com/book/info"
    params = dict(bookId=bookId)
    r = session.get(url, params=params)
    isbn = ""
    if r.ok:
        data = r.json()
    return data



def update(date,rating,note, status,page_id):
    properties = {
        "读完日期": {"date": {"start": date.strftime("%Y-%m-%d %H:%M:%S"),"time_zone": "Asia/Shanghai"}},
        "状态": {"status": {"name": status}},
    }
    if note != "":
        properties["概要"] = {"rich_text": [{"type": "text", "text": {"content": note}}]}
    client.pages.update(page_id=page_id, properties=properties)

def insert_movie(title, date, link, cover, rating, note, status, year, directors, actors, genre, country, imdb):
    """插入到notion"""
    time.sleep(0.3)
    parent = {
        "database_id": database_id,
        "type": "database_id"
    }
    # 将两个列表合并去重
    authors = list(set(directors + actors))

    # 生成字典列表
    authors = [{"name": x} for x in authors]
    properties = {
        "Name": {"title": [{"type": "text", "text": {"content": title}}]},
        "读完日期": {"date": {"start": date.strftime("%Y-%m-%d %H:%M:%S"),"time_zone": "Asia/Shanghai"}},
        "URL": {"url": link},
        "概要": {"rich_text": [{"type": "text", "text": {"content": note}}]},
        "Author": {"multi_select": authors},
        "类型": {"status": {"name": "电影"}},
        "状态": {"status": {"name": status}},
        "附件": {"files": [{"type": "external", "name": "Cover", "external": {"url": cover}}]},
    }
    icon = {
        "type": "external",
        "external": {
            "url": cover
        }
    }
    response = client.pages.create(
        parent=parent, icon=icon, properties=properties)
    id = response["id"]
    return id

def insert_douban_book(title, date, link, cover, info, rating, note, status):
    """插入到notion"""
    time.sleep(0.3)
    parent = {
        "database_id": database_id,
        "type": "database_id"
    }
    authors  =  result_list = [{"name": x} for x in info['作者']]
    properties = {
        "Name": {"title": [{"type": "text", "text": {"content": title}}]},
        "读完日期": {"date": {"start": date.strftime("%Y-%m-%d %H:%M:%S"),"time_zone": "Asia/Shanghai"}},
        "URL": {"url": link},
        "概要": {"rich_text": [{"type": "text", "text": {"content": note}}]},
        "Author": {"multi_select": authors},
        "类型": {"status": {"name": "书籍"}},
        "状态": {"status": {"name": status}},
        "附件": {"files": [{"type": "external", "name": "Cover", "external": {"url": cover}}]},
    }
    icon = {
        "type": "external",
        "external": {
            "url": cover
        }
    }
    response = client.pages.create(
        parent=parent, icon=icon, properties=properties)
    id = response["id"]
    return id

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("weread_cookie")
    parser.add_argument("notion_token")
    parser.add_argument("database_id")
    parser.add_argument("douban_user_id")
    options = parser.parse_args()
    weread_cookie = options.weread_cookie
    database_id = options.database_id
    notion_token = options.notion_token
    douban_user_id = options.douban_user_id
    session = requests.Session()
    session.cookies = parse_cookie_string(weread_cookie)
    client = Client(
        auth=notion_token,
        log_level=logging.ERROR
    )
    url = f'https://www.douban.com/feed/people/{douban_user_id}/interests'
    feed_parser()
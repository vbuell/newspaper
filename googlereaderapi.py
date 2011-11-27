#! /usr/bin/python
# -*- coding: iso-8859-1 -*-
#
#
# googlereaderapi.py
# 
# A python wrapper for the Google Reader
#
# Copyright (C) 2011 Lorenzo Carbonell
# lorenzo.carbonell.cerezo@gmail.com
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

__author__ = 'Lorenzo Carbonell <lorenzo.carbonell.cerezo@gmail.com>'
__date__ = '$13/03/2011'
__copyright__ = 'Copyright (c) 2011 Lorenzo Carbonell'
__license__ = 'GPLV3'
__url__ = 'http://www.atareao.es'

import simplejson
import urllib
import urllib2
from lxml.html.clean import clean_html
import time
import logging

class Article(object):
    def __init__(self, elemento):
        self.is_read = False
        self.is_marked_as_unread = False
        self.is_liked = False
        self.is_shared = False
        self.is_starred = False
        self.is_browsed = False
        self.is_emailed = False
        self.is_twitter = False
        self.is_readitlater = False
        #
        self.crawlTimeMsec = self._get(elemento, 'crawlTimeMsec')
        self.id = self._get(elemento, 'id')
        self.categories = self._get(elemento, 'categories')
        self.title = self._get(elemento, 'title')
        self.alternate = self._get(elemento, 'alternate')
        if len(self.alternate) > 0:
            self.alternate = self.alternate[0]
        self.published = self._get(elemento, 'published')
        self.updated = self._get(elemento, 'updated')
        self.summary = self._get(elemento, 'summary')
        if self.summary is not None:
            self.summary = clean_html('<div>%s</div>' % (self.summary['content']))
        self.content = self._get(elemento, 'content')
        if self.content is not None:
            self.content = clean_html('<div>%s</div>' % (self.content['content']))
        self.author = self._get(elemento, 'author')
        self.likingUsers = self._get(elemento, 'likingUsers')
        self.comments = self._get(elemento, 'comments')
        self.annotations = self._get(elemento, 'annotations')
        self.origin = self._get(elemento, 'origin')

    # origin['streamId']
    # origin['title']
    # origin['htmlUrl']

    def _get(self, elemento, key):
        if key in elemento:
            return elemento[key]
        return None


class GoogleReader(object):
    def __init__(self, username, password):
        self.client = 'news'
        self.username = username
        self.email = username
        self.password = password
        self.noticias = []
        self.get_header()

    def get_header(self):
        # Authenticate to obtain Auth
        auth_url = 'https://www.google.com/accounts/ClientLogin'
        auth_req_data = urllib.urlencode({
            'Email': self.username,
            'Passwd': self.password,
            'service': 'reader',
            'source': self.client
        })
        auth_req = urllib2.Request(auth_url, data=auth_req_data)
        auth_resp = urllib2.urlopen(auth_req)
        auth_resp_content = auth_resp.read()
        auth_resp_dict = dict(x.split('=') for x in auth_resp_content.split('\n') if x)
        AUTH = auth_resp_dict['Auth']
        # Create a cookie in the header using the Auth
        self.header = {'User-Agent': 'Magic Browser', 'Authorization': 'GoogleLogin auth=%s' % AUTH}
        self.get_token()

    def get_token(self):
        reader_url = 'https://www.google.com/reader/api/0/token'
        reader_req = urllib2.Request(reader_url, None, self.header)
        answer = urllib2.urlopen(reader_req)
        self.token = answer.read()
        return self.token


    def _mark_as(self, action, entryid, mark):
        if mark:
            option = 'a'
        else:
            option = 'r'
        post_data = urllib.urlencode({'i': entryid,
                                      option: 'user/-/state/com.google/%s' % (action),
                                      'ac': 'edit',
                                      'T': self.token})
        print post_data
        url = 'http://www.google.com/reader/api/0/edit-tag'
        request = urllib2.Request(url, post_data, self.header)
        try:
            f = urllib2.urlopen(request)
        except Exception, e:
            logging.exception("urlopen error:")
            # Authorization finished
            self.get_header()
            url = 'http://www.google.com/reader/api/0/edit-tag'
            request = urllib2.Request(url, post_data, self.header)
            f = urllib2.urlopen(request)
        result = f.read()
        if result == 'OK':
            return True
        else:
            self.get_token()
            url = 'http://www.google.com/reader/api/0/edit-tag'
            request = urllib2.Request(url, post_data, self.header)
            f = urllib2.urlopen(request)
            result = f.read()
            if result == 'OK':
                return True
        self.get_token()
        return False

    def mark_as_starred(self, entryid, is_marked):
        return self._mark_as('starred', entryid, is_marked)

    def mark_as_kept_unread(self, entryid, is_marked):
        return self._mark_as('tracking-kept-unread', entryid, is_marked)

    def mark_as_shared(self, entryid, is_marked):
        return self._mark_as('broadcast', entryid, is_marked)

    def mark_as_browsed(self, entryid, is_marked):
        return self._mark_as('tracking-item-link-used', entryid, is_marked)

    def mark_as_emailed(self, entryid, is_marked):
        return self._mark_as('tracking-emailed', entryid, is_marked)

    def mark_as_like(self, entryid, is_marked):
        return self._mark_as('like', entryid, is_marked)

    def mark_as_read(self, entryid, is_marked):
        return self._mark_as('read', entryid, is_marked)

    def get_shared_list(self, number_of_items=20, from_past_to_now=True):
        shared = []
        url = 'https://www.google.com/reader/api/0/stream/contents/user/-/state/com.google/broadcast%s'
        if from_past_to_now:
            r = 'o'
        else:
            r = 'd'
        get_data = urllib.urlencode({'n': str(number_of_items),
                                     'ck': int(time.time()),
                                     'r': r,
                                     'client': self.client})
        # Doing GET
        reader_url = url % (get_data)
        request = urllib2.Request(reader_url, None, self.header)
        f = urllib2.urlopen(request)
        if f:
            return simplejson.loads(f.read())
        return None

        '''
      def mark_all_as_read(self, SID):
         url    = 'http://www.google.com/reader/api/0/mark-all-as-read?client=contact:%s" % (self.login)
         data   = { 's': 'user/06091295523448519803/state/com.google/reading-list',
                    't': 'All%20items',
                    'T': self._get_token(SID),
                    'ts': int(time.time())
                  }
         result = self.cm.post(url, self._header(), data, self._cookie(SID))
         if result: pass
         else: print 'Error: mark_all_as_read'
         '''

    def get_reading_list(self, number_of_items=20, from_past_to_now=True, continuation=None):
        shared = []
        url = 'https://www.google.com/reader/api/0/stream/contents/user/-/state/com.google/reading-list?%s'
        if from_past_to_now:
            r = 'o'
        else:
            r = 'd'
        map = {'n': str(number_of_items),
                                     'ck': int(time.time()),
                                     'r': r,
                                     'client': self.client,
                                     'xt': 'user/-/state/com.google/read'}
        if continuation:
            map['c'] = continuation
        get_data = urllib.urlencode(map)
        # Doing GET
        reader_url = url % (get_data)
        request = urllib2.Request(reader_url, None, self.header)
        f = urllib2.urlopen(request)
        if f:
            return simplejson.loads(f.read())
        return None

    def get_entries(self, feed_id, number_of_items=20, from_past_to_now=True, continuation=None):
        url =      'http://www.google.com/reader/api/0/stream/contents/%s?%s'#ot=1317981600&r=n&xt=user%2F15348108177535720089%2Fstate%2Fcom.google%2Fread&likes=false&comments=false&n=20&ck=1320576432916&client=scroll
#        url = 'https://www.google.com/reader/api/0/stream/contents/user/-/label/%s?%s'
        if from_past_to_now:
            r = 'o'
        else:
            r = 'd'
        map = {'n': str(number_of_items),
                                     'ck': int(time.time()),
                                     'r': r,
                                     'client': self.client,
                                     'xt': 'user/-/state/com.google/read'}
        if continuation:
            map['c'] = continuation
        get_data = urllib.urlencode(map)
        # Doing GET
        reader_url = url % (urllib.quote(feed_id), get_data)
        print "^^^^^^^^^^^",reader_url
        request = urllib2.Request(reader_url, None, self.header)
        f = urllib2.urlopen(request)
        if f:
            return simplejson.loads(f.read())
        return None

    def get_unread_count(self):
        reader_base_url = 'http://www.google.com/reader/api/0/unread-count?%s'
        reader_req_data = urllib.urlencode({'all': 'true',
                                            'output': 'json',
                                            'ck': int(time.time()),
                                            'client': self.client})
        reader_url = reader_base_url % (reader_req_data)
        reader_req = urllib2.Request(reader_url, None, self.header)
        reader_resp = urllib2.urlopen(reader_req)
        if reader_resp:
            j = simplejson.loads(reader_resp.read())
            count = ([c['count'] for c in j['unreadcounts'] if c['id'].endswith('/state/com.google/reading-list')] or [0])[0]
            return count, j
        return None

    def get_subscriptions(self):
        url = 'http://www.google.com/reader/api/0/subscription/list?%s'
        get_data = urllib.urlencode({'ck': int(time.time()),
                                     'output': 'json',
                                     'client': self.client})
        # Doing GET
        reader_url = url % get_data
        print reader_url
        request = urllib2.Request(reader_url, None, self.header)
        f = urllib2.urlopen(request)
        if f:
            obj = simplejson.loads(f.read())
            return obj
        return None

    def search(self, keywords, limit=1000):
        # Search
        url = 'http://www.google.com/reader/api/0/search/items/ids?%s'
        get_data = urllib.urlencode({'q': keywords,
                                     'num': limit,
                                     'output': 'json',
                                     'ck': int(time.time()),
                                     'client': self.client})
        # Doing GET
        reader_url = url % get_data
        request = urllib2.Request(reader_url, None, self.header)
        f = urllib2.urlopen(request)
        entryids = []
        if f:
            obj = simplejson.loads(f.read())
            entryids = [c['id'] for c in obj['results']]

        logging.info("googlereaderapi: Search result: " + str(len(entryids)))

        # FIXME: We need to implement paging. Google can retreive only 250 items at once.

        p = {'i': entryids,
             'T': [self.token]}
        post_data = urllib.urlencode([(k, v) for k, vs in p.items() for v in vs])

        url = 'http://www.google.com/reader/api/0/stream/items/contents?%s'
        get_data = urllib.urlencode({'likes': 'false',
                                     'comments': 'false',
                                     'ck': int(time.time()),
                                     'client': self.client})
        reader_url = url % get_data
        request = urllib2.Request(reader_url, post_data, self.header)
        f = urllib2.urlopen(request)
        obj = simplejson.loads(f.read())

        return obj

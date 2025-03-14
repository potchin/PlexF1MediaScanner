#!/usr/bin/env python

#     Copyright (C) 2013  Casey Duquette
#
#     This program is free software; you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation; either version 2 of the License, or
#     (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.

"""
Custom scanner plugin for Plex Media Server for Formula 1 Broadcasts.

Some notes:
    - this runs in a python 2.7 environment(!) so no fancy f-strings, ordered dictionaries etc

"""

import re, os, os.path
import sys
import logging
import urllib
import ssl
import json
from time import sleep
from pprint import pformat

# plex probably sets this itself. maybe.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Plug-ins-*/Scanners.bundle/Contents/Resources/Common/")))

import Media, VideoFiles, Stack

LOG_FILE = '/tmp/Formula1.log'
DOWNLOAD_ART = True

regexes = [
    # Formula.1.2020x05.70th-Anniversary-GB.Race.SkyF1HD.1080p/02.Race.Session.mp4
    ("smcgill1969", 'Formula.1[\._ ](?P<year>[0-9]{4})x(?P<raceno>[0-9]{2})[\._ ](?P<location>.*)[\._ ](?P<session>.*?).SkyF1U?HD.(1080p|SD)/(?P<episode>.*?)[\._ ](?P<description>.*?).mp4'),
    # 01.F1.2024.R24.Abu.Dhabi.Grand.Prix.Drivers.Press.Conference.Sky.Sports.F1.UHD.2160P.mkv
    ("egortech", '(?P<episode>[0-9]{2}).F1.(?P<year>[0-9]{4}).R(?P<raceno>[0-9]{2}).(?P<location>.*?).Grand.Prix.(?P<description>.*?).Sky.Sports.F1.UHD.(?P<quality>[0-9]+(P|p)).mkv'),
    # Fallback should always be last
    ("fallback", '.*.(mp4|mkv)')
]

sessions = {}
sessions['Practice'] = 1
sessions['Qualifying'] = 2
sessions['Race'] = 3

def remove_prefix(s, prefix):
    return s[len(prefix):] if s.startswith(prefix) else s


def download_url(url, filename):
    try:
        insecure_context = ssl._create_unverified_context()
        urllib.urlretrieve(url, filename, context=insecure_context)
        os.chmod(filename, 0666)
    except IOError as e:
        logging.error("Unable to download from url: %s to %s. Error: %s" % (url, filename, e))

def download_art(filename, art_type, season, round, session, event, allow_fake=False):
    """Download and save artwork from thesportsdb

    season = year
    round = raceno
    event = eg "Australian Grand Prix"
    session = Practice/Race/something
    """
    if os.path.exists(filename):
        return

    found = False
    if round == 0:
        logging.warn("Found invalid round, file may not be for a race weekend, eg testing")
        allow_fake = True
    else:
        logging.debug("Downloading artwork to: %s" % filename)

        try:
            insecure_context = ssl._create_unverified_context()
            dataurl = ' https://www.thesportsdb.com/api/v1/json/3/eventsround.php?id=4370&r=%s&s=%s' % (round, season)
            logging.info("Pulling data from: %s" % dataurl)
            eventdata = urllib.urlopen(dataurl, context=insecure_context)
            sleep(2) #sportsdb API limit
            eventdata = json.loads(eventdata.read())

            # try to get an aimage specific to this session
            for event in eventdata['events']:
                # logging.critical(pformat(event))
                # session is likely race/practice/qualy/sprint

                if " shootout " in session.lower():
                    session = "Sprint Shootout"
                elif " sprint " in session.lower():
                    session = "Grand Prix Sprint"
                elif " qualifying " in session.lower():
                    session = "Qualifying"
                elif " race " in session.lower():
                    session = "Grand Prix"

                if event['strEvent'].lower().endswith(session.lower()):
                    if event[art_type]:
                        download_url(event[art_type], filename)
                        found = True

            # get any image for this round instead
            if not found:
                for event in eventdata['events']:
                    if event[art_type]:
                        download_url(event[art_type], filename)
                        found = True
        except Exception as e:
            logging.critical("Unable to download artwork... %s" % e)

    if not found:
        if allow_fake:
            if art_type == "strPoster":
                download_url("https://www.thesportsdb.com/images/media/league/poster/4e1svi1605133041.jpg", filename)
            else:
                download_url("https://github.com/potchin/PlexF1MediaScanner/raw/master/episode_poster.png", filename)
        else:
            logging.warn("Unable to find art for event")
    return


# Look for episodes.
def Scan(path, files, mediaList, subdirs, language=None, root=None):
    logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG)
    logging.debug('Called Scan() with: path=%s, files=%s, mediaList=%s, subdirs=%s, language=%s, root=%s',
                 path, files, mediaList, subdirs, language, root)
    # Scan for video files.
    VideoFiles.Scan(path, files, mediaList, subdirs, root)

    # Run the select regexp for all media files.
    for i in files:
        try:
            logging.debug('Processing: %s' % i)
            file = remove_prefix(i, root + '/')
            found = False
            for regex_name, episode_regexp in regexes:
                if found:
                    break # no point re-processing a file that has already been processed
                match = re.search(episode_regexp, file)
                if match:
                    if regex_name == "fallback":
                        logging.debug('Using FALLBACK regex for %s', file)
                        try:
                            year = int(re.search(r'(?:19|20)\d{2}', file).group(0)) if re.search(r'(?:19|20)\d{2}', file) else 2025
                            description = file.rsplit('.', 1)[0].replace(".", " ") # remove file extension and replace dots with spaces
                            tv_show = Media.Episode(
                                description,    # show (inc year(season))
                                0,              # season. Must be int, strings are not supported :(
                                0,              # episode, indexed the files for a given show/location
                                file,           # includes location string and ep name i.e. Spain Grand Prix Qualifying
                                int(year))      # the actual year detected, same as used in part of the show name

                        except Exception as e:
                            logging.error(e)

                        logging.debug("tv_show created")
                        tv_show.parts.append(i)
                        logging.debug("part added to tv_shows")
                        mediaList.append(tv_show)
                        logging.debug("added tv_show to mediaList")
                        break
                    found = True
                    logging.debug("regex for %s MATCHED file: %s" % (regex_name, file))

                    # Extract data.
                    show = 'Formula 1'
                    year = int(match.group('year').strip())
                    # show = "%s %s" % (show, year) # Make a composite show name like Formula1 + yyyy
                    location = match.group('location').replace("-"," ").replace("."," ")
                    # episode is just a meaningless index to get the different FP1-3, Qualifying, Race and other files to
                    # be listed under a location i.e. Spain, which again is mapped to season number - as season can not contain a string
                    episode = int(match.group('episode').strip())

                    if "session" in match.groupdict():
                        # smcmgill releases are in different folders for each session (eg race, qualy)
                        # and each folder will show as a different TV Season
                        session = sessions[match.group('session')]
                        description = (location + " " + session).replace("."," ") # re-use the session name
                        library_name = "%sx%s: %s %s" %(year, match.group('raceno'), location, session)
                    else:
                        # igortech will have a TV season for each weekend
                        session = match.group('raceno')
                        description = match.group('description').replace(".", " ")
                        library_name = "%sx%s: %s GP Weekend" %(year, match.group('raceno'), location)


                    logging.debug("session: %s" % session)
                    logging.debug("location: %s" % location)
                    logging.debug("episode: %s" % episode)
                    logging.debug("description: %s" % description)
                    logging.debug("library_name: %s" % library_name)

                    if DOWNLOAD_ART:
                        posterfile=os.path.dirname(i)+"/poster.jpg"
                        download_art(posterfile, "strPoster", year, int(match.group('raceno')), session, location)

                        thumbnail=i[:-3]+"jpg"
                        download_art(thumbnail, "strThumb", year, int(match.group('raceno')), session, location, allow_fake=True)

                        fanart=os.path.dirname(i)+"/fanart.jpg"
                        download_art(fanart, "strThumb", year, int(match.group('raceno')), session, location)

                    try:
                        tv_show = Media.Episode(
                            library_name,         # show (inc year(season))
                            session,              # season. Must be int, strings are not supported :(
                            episode,              # episode, indexed the files for a given show/location
                            description,          # includes location string and ep name i.e. Spain Grand Prix Qualifying
                            year)                 # the actual year detected, same as used in part of the show name

                    except Exception as e:
                        logging.error(e)

                    logging.debug("tv_show created")
                    tv_show.parts.append(i)
                    logging.debug("part added to tv_shows")
                    mediaList.append(tv_show)
                    logging.debug("added tv_show to mediaList")
                else:
                    logging.debug("regex for %s FAILED to match file: %s" % (regex_name, file))

        except Exception as e:
            logging.error("Exception details: %s" % e)
            logging.error("Full traceback:", exc_info=True)
    # This doesnt seem to happen often (ever?)
    for s in subdirs:
        nested_subdirs = []
        nested_files = []
        for z in os.listdir(s):
            if os.path.isdir(os.path.join(s, z)):
                nested_subdirs.append(os.path.join(s, z))
            elif os.path.isfile(os.path.join(s, z)):
                nested_files.append(os.path.join(s, z))
        # This should be safe, since we're not following symlinks or anything that might cause a loop.
        Scan(s, nested_files, mediaList, nested_subdirs, root=root)

    # Stack the results.
    Stack.Scan(path, files, mediaList, subdirs)

if __name__ == '__main__':
  print("You're not plex!")
  if sys.version_info.major != 2 or sys.version_info.minor != 7:
    print("Warning: Python %d.%d detected. Scanner runs under Python 2.7 in Plex" % (sys.version_info.major, sys.version_info.minor))
  path = sys.argv[1]
  files = [os.path.join(path, file) for file in os.listdir(path)]
  media = []
  Scan(path[1:], files, media, [])
  print("F1: media |", media, "|")

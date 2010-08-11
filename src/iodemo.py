#!/usr/bin/python2.4
#
# Copyright 2010 Google Inc. All Rights Reserved.

# pylint: disable-msg=C6310

"""Trivia Quiz.

This module demonstrates the App Engine Channel API by implementing a
multiplayer trivia quiz.
"""

import datetime
import logging
import os
import random
from django.utils import simplejson
from google.appengine.api import channel
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app


questions = [
    {'q': "When Google's founders were at Stanford, what was the name they gave their search engine?", 'a': ['BackRub', 'Linkerator', 'Alta Vista', 'Googol']},
    {'q': "What University were Google's co-founders studying at when they started Google?", 'a': ['Stanford', 'Princeton', 'MIT', 'The Evergreen State College']},
    {'q': "Google's first international office was opened in 2001 in what city?", 'a': ['Tokyo', 'London', 'Sydney', 'Tijuana']},
    {'q': "What is the nickname for Google's first major update to the Android operating system?", 'a': ['Cupcake', 'Donut', 'Eclair', 'Creampuff']},
    {'q': "What year was Google incorporated?", 'a': ['1998', '2001', '1991', '1999']},
    {'q': "What is the name of the link analysis algorithm that powers Google search?", 'a': ['PageRank', 'Brindle', 'BackRub', 'The Edge']},
    {'q': "What do the two buttons under the search box on Google's homepage say?", 'a': ['Google Search, I\'m Feeling Lucky', 'Search the Web, Find my Keys', 'Find, Lucky', 'Go, Stop']},
    {'q': "What is the name of Google's web browser?", 'a': ['Chrome', 'GBrowse', 'Iron', 'Chromium']},
    {'q': "Which British mathemetician is often considered to be the father of modern computer science?", 'a': ['Alan Turing', 'Walter Pitts', 'John von Neumann', 'Oliver Selfridge']},
    {'q': "What programming language makes use of the 'car' and 'cdr' expressions?", 'a': ['Lisp', 'Logo', 'Python', 'Prolog']},
    {'q': "Who is still writing \"The Art of Computer Programming?\"", 'a': ['Donald Knuth', 'Dennis Ritchie', 'Ravi Sethi', 'Jeffrey Ullman']},
    {'q': "Who usually spies on Alice and Bob?", 'a': ['Eve', 'Adam', 'Zorro', 'Chuck']},
    {'q': "What variable naming convention typically includes the data type at the beginning of the variable name?", 'a': ['Hungarian Notation', 'Reverse Polish Notation', 'rgchNaming', 'Type-inclusive Naming']},
    {'q': "Which computer operating system was originally developed in 1969 by a group of AT&T employees at Bell Labs?", 'a': ['Unix', 'Linux', 'Multics', 'OS/9']},
    {'q': "What is the worst case runtime of quicksort?", 'a': ['O(n^2)', 'O(n)', 'O(2^n)', 'O(1)']},
    {'q': "Who is the Linux mascot?", 'a': ['Tux', 'Clippy', 'Rover', 'Linus']},
    {'q': "Which computer language was named after a French mathematician and philosopher?", 'a': ['Pascal', 'Ada', 'COBOL', 'Mandelbrot']},
    {'q': "According to the Hitchiker's Guide to the Galaxy, what is the answer to Life, The Universe and Everything?", 'a': ['42', 'Pancakes', 'Cupcakes', '43']},
    {'q': "Who is the author of an online comic with the tagline 'A webcomic of romance, sarcasm, math, and language?'", 'a': ['Randall Munroe', 'Jim Davis', 'Allie Brosh', 'Berkeley Breathed']},
    {'q': "Who wrote the Foundation Series?", 'a': ['Isaac Asimov', 'Neal Stephenson', 'Philip K. Dick', 'Randall Munroe']},
]


class UserData(db.Expando):
  """All the data we store with a given user."""
  user = db.UserProperty()
  display_name = db.StringProperty()
  score = db.IntegerProperty()
  available_questions = db.ListProperty(int)
  last_update_time = db.DateTimeProperty(auto_now=True)
  shard = db.IntegerProperty()


class Broadcaster(object):
  """Sends a message to all users within the given user's shard."""

  def __init__(self, sending_user):
    self.sending_user = sending_user

  def BroadcastMessage(self, message):
    """Send the given message to all users in this user's shard."""
    users_in_shard = db.GqlQuery("SELECT * FROM UserData where shard = :shard",
                                 shard=self.sending_user.shard)
    for user in users_in_shard:
      if (datetime.datetime.now() - user.last_update_time
          > datetime.timedelta(hours=1)):
        logging.info("Removing user: " + user.display_name)
        user.delete()
      else:
        if (self.sending_user is None or
            user.user.user_id() != self.sending_user.user.user_id()):
          messager = UserMessager(user.user.user_id())
          messager.Send(message)

  def GetScores(self):
    """Send the scores in this shard to the user."""
    users_in_shard = db.GqlQuery("SELECT * FROM UserData where shard = :shard",
                                 shard=self.sending_user.shard)
    scores = []
    for user in users_in_shard:
      scores.append({'u': user.display_name,
                     's': user.score,
                     't': len(questions) - len(user.available_questions) - 1})
    scores.sort()
    scores.reverse()
    return scores[:8]


class UserMessager(object):
  """Sends a message to a given user."""

  def __init__(self, user_id):
    self.user = user_id

  def CreateChannelId(self):
    logging.info("Create channel: " + self.user)
    return channel.create_channel(self.user)

  def Send(self, message):
    channel.send_message(self.user, simplejson.dumps(message))

  def SendNewQuestionToUser(self, user_data, opt_message=None):
    """Send a new question to the given user."""
    if user_data is not None:
      if not user_data.available_questions:
        question_id = -1
      else:
        question_id = random.choice(user_data.available_questions)
    else:
      question_id = random.randint(0, len(questions) - 1)

    if opt_message is None:
      message = {}
    else:
      message = opt_message

    if question_id >= 0:
      message['q'] = {
          'id': question_id,
          'q': questions[question_id]['q'],
          'a': questions[question_id]['a'][:]
      }
      random.shuffle(message['q']['a'])
    else:
      message['c'] = True

    self.Send(message)


class AnswerPage(webapp.RequestHandler):
  """The client posts an answer to a question to this page."""

  def post(self):
    """Handles an answer to a question."""
    user = users.get_current_user()
    if user:
      messager = UserMessager(user.user_id())
      question_id = int(self.request.get('q'))
      update_message = None
      user_data = UserData.get_by_key_name(user.user_id())

      if user_data.available_questions.count(question_id) > 0:
        answer = self.request.get('a')
        correct_answer = questions[question_id]['a'][0]
        was_correct = answer == correct_answer

        if was_correct:
          user_data.score += 1
        user_data.available_questions.remove(question_id)
        db.put(user_data)
        update_message = {'a': {'type': 'r',
                                'u': user_data.display_name,
                                'r': was_correct,
                                's': user_data.score,
                                'q': questions[question_id]['q']},
                          's': Broadcaster(user_data).GetScores()}
        Broadcaster(user_data).BroadcastMessage(update_message)
        update_message['r'] = {'c': was_correct, 'a': correct_answer}

      messager.SendNewQuestionToUser(user_data, update_message)
      self.response.out.write('ok')
    else:
      self.response.set_status(401)


class ConnectedPage(webapp.RequestHandler):
  """This page is requested when the client is successfully connected to the channel."""

  def post(self):
    user = users.get_current_user()
    if user:
      user_data = UserData.get_or_insert(user.user_id(), user=user, score=0,
                                         available_questions=range(0, len(questions) - 1))
      messager = UserMessager(user.user_id())
      messager.SendNewQuestionToUser(user_data)


class SetNamePage(webapp.RequestHandler):
  """Page to set the display name of the user."""

  def post(self):
    user = users.get_current_user()
    if user:
      user_data = UserData.get_or_insert(user.user_id(), user=user, score=0,
                                         available_questions=range(0, len(questions) - 1),
                                         shard=UserData.all().count() / 10)
      user_data.display_name = self.request.get('n')
      db.put(user_data)
      Broadcaster(user_data).BroadcastMessage({'a': {'type': 'j', 'u': user_data.display_name}})


class StartOverPage(webapp.RequestHandler):
  """Page to indicate a user wants to start the quiz over."""

  def post(self):
    """Starts the game over for the current user."""
    user = users.get_current_user()
    if user:
      user_data = UserData.get_or_insert(user.user_id())
      user_data.user = user
      user_data.score = 0
      user_data.available_questions = range(0, len(questions) - 1)
      db.put(user_data)
      UserMessager(user.user_id()).SendNewQuestionToUser(user_data, {'s': Broadcaster(user_data).GetScores()})


class MainPage(webapp.RequestHandler):
  """The main UI page, renders the 'index.html' template."""

  def get(self):
    """Renders the main page."""
    user = users.get_current_user()
    if user:
      messager = UserMessager(user.user_id())
      channel_id = messager.CreateChannelId()
      user_data = UserData.get_or_insert(user.user_id(), user=user, score=0,
                                         available_questions=range(0, len(questions) - 1),
                                         display_name=user.nickname(),
                                         shard=UserData.all().count() / 10)
      if user_data.display_name is not None:
        nickname = user_data.display_name
      else:
        nickname = user.nickname()
      template_values = {'channel_id': channel_id,
                         'nickname': nickname,
                         'initial_messages': simplejson.dumps(
                             {'s': Broadcaster(user_data).GetScores()})}
      path = os.path.join(os.path.dirname(__file__), 'index.html')
      self.response.out.write(template.render(path, template_values))
    else:
      self.redirect(users.create_login_url(self.request.uri))


application = webapp.WSGIApplication([
    ('/', MainPage),
    ('/answer', AnswerPage),
    ('/setname', SetNamePage),
    ('/startover', StartOverPage),
    ('/connected', ConnectedPage)], debug=True)


def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()

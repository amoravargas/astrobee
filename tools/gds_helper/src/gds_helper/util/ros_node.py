import time

import rospy

# from utils import Queue
from util.utils import Queue


class RosNode(object):
    def __init__(self, name, anonymous=True, disable_signals=False):
        self.name = name
        self.anonymous = anonymous
        self.disable_signals = disable_signals
        self.subscribers = {}
        self.publishers = {}

    def run(self):
        rospy.init_node(
            self.name, anonymous=self.anonymous, disable_signals=self.disable_signals
        )
        rospy.on_shutdown(self.on_shutdown)

    def add_subscriber(self, key, topic, callback, msg_type):
        self.subscribers[key] = rospy.Subscriber(topic, msg_type, callback)

    def get_subscriber(self, key):
        return self.subscribers.get(key, None)

    def add_publisher(self, key, topic, type, queue_size=10, latch=False):
        self.publishers[key] = rospy.Publisher(
            topic, type, queue_size=queue_size, latch=latch
        )

    def get_publisher(self, key):
        return self.publishers.get(key, None)

    def __check_subscriber_topics(self):
        topics = rospy.get_published_topics()
        for k, sub in self.subs:
            pass

    def shutdown(self, reason=""):
        if self.disable_signals:
            rospy.signal_shutdown(reason)

    def on_shutdown(self):
        pass

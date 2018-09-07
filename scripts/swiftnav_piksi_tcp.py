#!/usr/bin/env python

import subprocess
import os
import struct
import time
import sys
import rospy
import numpy as np
import math
from sbp.client.drivers.network_drivers import TCPDriver
from sbp.client import Handler, Framer
from sbp.settings import SBP_MSG_SETTINGS_READ_RESP, MsgSettingsWrite, MsgSettingsReadReq
from sbp.imu import SBP_MSG_IMU_RAW
from sbp.navigation import SBP_MSG_BASELINE_HEADING_DEP_A, SBP_MSG_POS_LLH, SBP_MSG_BASELINE_NED
from datetime import datetime
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu, MagneticField, NavSatFix
from std_msgs.msg import String, Int32, Bool
from geometry_msgs.msg import TwistStamped


class SwiftNavDriver(object):

    def __init__(self):
        rospy.loginfo("[RR_SWIFTNAV_PIKSI] Initializing")

        # Initialize message and publisher structures
        self.drive_direction = "forward"
        self.ncat_process = None
        self.old_x = 0
        self.old_y = 0

        # TOPIC: swift_gps/llh/fix_mode
        # This topic reports the fix_mode of llh position
        # 0 - Invalid 
	# 1 - Single Point Position (SSP)
	# 2 - Differential GNSS (DGNSS)
	# 3 - Float RTK
	# 4 - Fixed RTK
	# 5 - Dead Reckoning
        # 6 - Satellite-based Augmentation System (SBAS)

	# ROS Publishers
	self.pub_imu = rospy.Publisher('/swift_gps/imu/raw', Imu, queue_size=10)
	self.pub_llh = rospy.Publisher('/swift_gps/llh/position', NavSatFix, queue_size=3)
	self.pub_llh_n_sats = rospy.Publisher('/swift_gps/llh/n_sats', Int32, queue_size=3)
	self.pub_llh_fix_mode = rospy.Publisher('/swift_gps/llh/fix_mode', Int32, queue_size=3)
	self.pub_ecef_odom = rospy.Publisher('/swift_gps/baseline/ecef/position', Odometry, queue_size=3)

	# ROS Subscriber
	self.sub_rtk_cmd = rospy.Subscriber("/swift_gps/enable_comms", Bool, self.enable_comms_cb)
        self.sub_cmd_vel = rospy.Subscriber("/cmd_vel/managed", TwistStamped, self.cmd_vel_cb)            



    def cmd_vel_cb(self, cmd_vel):
        if cmd_vel.twist.linear.x > 0:
            self.drive_direction = "forward"
        if cmd_vel.twist.linear.x < 0:
            self.drive_direction = "reverse"

    def enable_comms_cb(self, msg):
        if (msg.data == True):
	    # Note: ncat is the linux networking tool used to tunnel the RTK data through the main PC
	    if (self.ncat_process is None):
	        self.ncat_process = subprocess.Popen('/usr/bin/ncat -l 1.2.3.55 55555 --sh-exec "/usr/bin/ncat 65.132.94.146 55555"', shell=True)
                rospy.loginfo("[RR_SWIFNAV_PIKSI] GPS comms enabled, ncat started")
	    else:
	        rospy.logwarn("[RR_SWIFTNAV_PIKSI] GPS comms already enabled, ignoring request")
        if (msg.data == False):
	    if (self.ncat_process is not None):
	        subprocess.call(["kill", "-9", "%d" % self.ncat_process.pid])
	        CAT_PROC.wait()
	        os.system('killall ncat')
                rospy.loginfo("[RR_SWIFT_NAV_PIKSI] GPS comms disables, ncat stopped")
	        self.ncat_process=None
	    else:
	        rospy.logwarn("[RR_SWIFTNAV_PIKSI] RTK GPS already disabled, ignoring request")

def publish_baseline_msg(msg, **metadata):
    if self.comms_disabled:
        return

    # Obtain position and accuracies and convert from mm to m
    x_pos = float(msg.e)/1000
    y_pos = float(msg.n)/1000
    z_pos = float(msg.d)/1000
    h_accuracy = float(msg.h_accuracy)/1000
    v_accuracy = float(msg.v_accuracy)/1000


    if (x_pos,y_pos) == (0.0,0.0):
        rospy.logwarn_throttle(10,"SwiftNav GPS baseline reported x=0 y=0. Message not published")
        return

    # Build the ROS Odometry message
    ecef_odom_msg = Odometry()
    ecef_odom_msg.child_frame_id = 'gps_link'
    ecef_odom_msg.header.stamp = rospy.Time.now()
    ecef_odom_msg.header.frame_id = 'map'
    ecef_odom_msg.pose.pose.position.x = x_pos
    ecef_odom_msg.pose.pose.position.y = y_pos
    ecef_odom_msg.pose.pose.position.z = 0

    # Calculate distance travelled since last RTK measurement
    if self.drive_direction=="forward":
        delta_x = x_pos - self.previous_x
        delta_y = y_pos - self.previous_y
    if self.drive_direction=="reverse":
        delta_x = self.previous_x - x_pos
        delta_y = self.previous_y - y_pos
    distance_travelled = np.sqrt(np.power(delta_x,2) + np.power(delta_y,2))

    # Normalize the orientation vector
    if (distance_travelled==0):
        delta_x_hat = 0
        delta_y_hat = 0
    else:
        delta_x_hat = delta_x / distance_travelled
        delta_y_hat = delta_y / distance_travelled

    if (distance_travelled>0.04):
        angle = np.arctan2(delta_y_hat, delta_x_hat)
        ecef_odom_msg.pose.pose.orientation.z = 1*np.sin(angle/2)
        ecef_odom_msg.pose.pose.orientation.w = np.cos(angle/2)

    # Update the old positions
    self.previous_x = x_pos
    self.previous_y = y_pos
        
    # Calculate the position covariances using the accuracy reported by the Piksi
    cov_x = cov_y = h_accuracy
        
    # Calculate the orientation covariance, the further we have moved the more accurate orientation is
    if (0<=distance_travelled and distance_travelled<=0.04):
        theta_accuracy = 1000
    elif(0.04<distance_travelled and distance_travelled<=0.01):
        theta_accuracy = 0.348
    elif(0.01<distance_travelled and distance_travelled<=0.4):
        theta_accuracy = 0.174
    elif(0.4<distance_travelled):
        theta_accuracy = 0.14
    else:
        theta_accuracy = -1
        rospy.logerr_throttle(5,"distance travelled was negative")

    cov_theta = theta_accuracy
    ecef_odom_msg.pose.covariance = [cov_x, 0, 0, 0, 0, 0,
                                        0, cov_y, 0, 0, 0, 0,
                                        0, 0, 0, 0, 0, 0,
                                        0, 0, 0, 0, 0, 0,
                                        0, 0, 0, 0, 0, 0,
                                        0, 0, 0, 0, 0, cov_theta]
    # Publish earth-centered-earth-fixed message
    pub_ecef_odom.publish(ecef_odom_msg)


def publish_imu_msg(msg, **metadata):
    imu_msg = Imu()
    imu_msg.header.stamp = rospy.Time.now()
    imu_msg.header.frame_id = 'gps_link'
    # acc_range scale settings to +- 8g (4096 LSB/g), gyro_range to +-1000 (32.8 LSB/deg/s)
    #ascale=1.0/4096.0
    #gscale=1.0/32.8
    # acc_range scale settings to +- 4g (8192 LSB/g), gyro_range to +-500 (65.6 LSB/deg/s)
    # output in meters per second-squared
    ascale=9.8/8192.0
    # output in radians per second
    gscale=3.14159/180/65.6
    imu_msg.angular_velocity.x = msg.gyr_x*gscale
    imu_msg.angular_velocity.y = msg.gyr_y*gscale
    imu_msg.angular_velocity.z = msg.gyr_z*gscale
    imu_msg.linear_acceleration.x = msg.acc_x*ascale
    imu_msg.linear_acceleration.y = msg.acc_y*ascale
    imu_msg.linear_acceleration.z = msg.acc_z*ascale
    imu_msg.orientation_covariance = [0,0,0,
                                      0,0,0,
                                      0,0,0]
    imu_msg.angular_velocity_covariance= [0,0,0,
                                          0,0,0,
                                          0,0,0.01]
    imu_msg.linear_acceleration_covariance= [0.01,0,0,
                                             0,0.01,0,
                                             0,0,0.01]
    # Publish to /gps/imu/raw
    pub_imu.publish(imu_msg)


def publish_llh_msg(msg, **metadata):
    rospy.logwarn("Publishing llh message")
    llh_msg = NavSatFix()
    llh_msg.latitude = msg.lat
    llh_msg.longitude = msg.lon
    llh_msg.altitude = msg.height
    llh_msg.position_covariance_type = 2
    llh_msg.position_covariance = [9,0,0,
                                   0,9,0,
                                   0,0,9]
    # Publish ROS messages
    pub_llh.publish(llh_msg)
    pub_llh_n_sats.publish(Int32(msg.n_sats))
    pub_llh_fix_mode.publish(Int32(msg.flags))


class SwiftMonitor(object):
    ## Class to monitor Settings via SBP messages
    def __init__(self):
        self.settings = []

    def capture_setting(self, sbp_msg, **metadata):
        """Callback to extract and store setting values from
        SBP_MSG_SETTINGS_READ_RESP
        Messages of any type other than SBP_MSG_SETTINGS_READ_RESP are ignored
        """
        if sbp_msg.msg_type == SBP_MSG_SETTINGS_READ_RESP:
            section, setting, value = sbp_msg.payload.split('\0')[:3]
            self.settings.append((section, setting, value))

    def wait_for_setting_value(self, section, setting, value, wait_time=5.0):
        """Function to wait wait_time seconds to see a
        SBP_MSG_SETTINGS_READ_RESP message with a user-specified value
        """
        expire = time.time() + wait_time
        ok = False
        while not ok and time.time() < expire:
            settings = filter(lambda x: (x[0], x[1]) == (section, setting), self.settings)
            # Check to see if the last setting has the value we want
            if len(settings) > 0:
                ok = settings[-1][2] == value

            time.sleep(0.1)
        return ok

    def clear(self, section=None, setting=None, value=None):
        match = map(lambda (x,y,z): all((section is None or x == section, setting is None or y == setting, value is None or z == value)), self.settings)
        keep = filter(lambda (setting,remove): not remove, zip(self.settings,match))
        self.settings[:] = map(lambda x: x[0], keep)

def sbp_print_setting(sbp_msg, **metadata):
    print sbp_msg

if __name__ == "__main__":
    rospy.init_node('rr_swiftnav_gps_node')
    swift_nav_driver = SwiftNavDriver()


    # ROS Parameters
    ipaddr = rospy.get_param('default_param', '1.2.3.10')
    tcp_port = rospy.get_param('default_param', '55555')


    # Create SwiftNav Callbacks
    monitor = SwiftMonitor()
    rospy.loginfo("[RR_SWIFTNAV_PIKSI] 0")
    with TCPDriver(ipaddr, tcp_port) as driver:
        with Handler(Framer(driver.read, driver.write)) as source:
            driver.flush()
            time.sleep(2)
            # Capture setting messages
            source.add_callback(monitor.capture_setting,SBP_MSG_SETTINGS_READ_RESP)
            source.add_callback(sbp_print_setting, SBP_MSG_SETTINGS_READ_RESP)
            rospy.loginfo("[RR_SWIFTNAV_PIKSI] 1")
            source.add_callback(publish_baseline_msg, SBP_MSG_BASELINE_NED)
            source.add_callback(publish_imu_msg,SBP_MSG_IMU_RAW)
            source.add_callback(publish_llh_msg,SBP_MSG_POS_LLH)
            rospy.loginfo("[RR_SWIFTNAV_PIKSI] 2")
            source.start
            rospy.loginfo("[RR_SWIFTNAV_PIKSI] 3")
    while not rospy.is_shutdown():
        time.sleep(0.1)
    rospy.spin()


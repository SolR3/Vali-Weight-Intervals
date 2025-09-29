#############################
# Subnet threshold constants
#############################
MIN_STAKE_THRESHOLD = 4000  # TODO - Need some way to verify this
                            # This is the value used by the taoyield site
MIN_VTRUST_THRESHOLD = 0.01
MAX_U_THRESHOLD = 100800  # 2 weeks


####################################
# Printer color threshold constants
####################################
VTRUST_ERROR_THRESHOLD = 0.2
VTRUST_WARNING_THRESHOLD = 0.1
UPDATED_ERROR_THRESHOLD = 1080  # 3x normal subnet tempo (360 blocks)
UPDATED_WARNING_THRESHOLD = 720  # 2x normal subnet tempo (360 blocks)


#######################
# Hotkeys and Coldkeys
#######################
RIZZO_COLDKEY = "5FuzgvtfbZWdKSRxyYVPAPYNaNnf9cMnpT7phL3s2T3Kkrzo"

# This is a fix to handle the subnets on which we're registered on
# multiple uids.
MULTI_UID_HOTKEYS = {
    20: "5ExaAP3ENz3bCJufTzWzs6J6dCWuhjjURT8AdZkQ5qA4As2o",
    86: "5F9FAMhhzZJBraryVEp1PTeaL5bgjRKcw1FSyuvRLmXBds86",
    123: "5GzaskJbqJvGGXtu2124i9YLgHfMDDr7Pduq6xfYYgkJs123",
    124: "5FKk6ucEKuKzLspVYSv9fVHonumxMJ33MdHqbVjZi2NUs124",
}

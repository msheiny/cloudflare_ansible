#!/usr/bin/python
#
#
# Michael Sheinberg <m.sheiny@gmail.com>

ANSIBLE_METADATA = {'status': ['preview'],
                    'supported_by': 'community',
                    'version': '1.0'}

DOCUMENTATION = '''
---
module: cloudflare_ratelimit
author: "Michael Sheinberg (@msheiny)"
requirements:
   - "python >= 2.6"
   - "cloudflare >= 1.5.1"
short_description: manage Cloudflare ratelimit rules
description:
   - "Manages rate limit rules via the Cloudflare pip module. Docs: U(https://github.com/cloudflare/python-cloudflare)"
'''

try:
    import CloudFlare
    HAS_CF = True
except ImportError:
    HAS_CF = False

from ansible.module_utils.basic import AnsibleModule


DEFAULT_ERROR_MSG = '<error>This request has been rate-limited.</error>'
THRESHOLD_MIN = 2
PERIOD_MIN = 2
THRESHOLD_MAX = 1000000
PERIOD_MAX = 86400


class CF_API(object):

    def __init__(self, zone, email=None, api=None):
        if email and api:
            self.cf = CloudFlare.CloudFlare(email=email, token=api)
        else:
            self.cf = CloudFlare.CloudFlare()

        try:
            self.zoneid = self.cf.zones.get(params=dict(name=zone))[0]['id']
        except IndexError:
            raise UserWarning("Zone '%s' not found" % zone)

    def list_zone_ratelimits(self):
        return self.cf.zones.rate_limits.get(self.zoneid)

    def create_ratelimit(self,
                         description,
                         disabled,
                         threshold,
                         period,
                         match,
                         action,
                         update=True):
        """
            Return False if existing ratelimit exists that is the same
            as incoming parameters
        """

        data = dict(
                disabled=disabled,
                description=description,
                period=period,
                threshold=threshold,
                action=action,
                match=match)

        # check for existing ratelimit rule based off url
        existing_id = self.get_existing_ratelimit_id(match['request']['url'])

        if update and existing_id:
            # Compare existing ratelimit and proposed parameters
            if not self.compare_existing_ratelimit(existing_id, data):
                return self.cf.zones.rate_limits.put(self.zoneid,
                                                     existing_id['id'],
                                                     data=data)
            # Ratelimit for that URL already exists and hasnt changed
            return False
        else:
            # Ratelimit for that url doesnt exist, lets make it
            return self.cf.zones.rate_limits.post(self.zoneid, data=data)

    def get_existing_ratelimit_id(self, url):
        # Get a list of all rate limits for zone
        limits = self.list_zone_ratelimits()

        try:
            for rl in limits:
                if rl['match']['request']['url'] == url:
                    return rl
        except IndexError:
            pass
        return None

    def compare_existing_ratelimit(self, ratelimit, proposed_changes):
        compare = ['action', 'match', 'disabled', 'period',
                   'threshold', 'disabled', 'description']
        the_same = True

        for x in compare:
            # iterate through comparison fields, if one of the values
            # are different, let downstream know
            if ratelimit[x] != proposed_changes[x]:
                the_same = False

        if the_same:
            return True
        else:
            return False


def main():
    # Standard ansible boilerplate
    module = AnsibleModule(
        argument_spec=dict(
            account_email=dict(default=None, type='str'),
            account_api_token=dict(default=None, no_log=True, type='str'),
            zone_identifier=dict(required=True, type='str'),
            state=dict(default='present', choices=['present', 'absent']),
            description=dict(default='', type='str'),
            disabled=dict(default=False, type='bool'),
            threshold=dict(default=60, type='int'),
            period=dict(default=60, type='int'),
            match_method=dict(default=['GET', 'POST'], type='list'),
            match_schemes=dict(default=['HTTP', 'HTTPS'], type='list'),
            match_url=dict(required=True, type='str'),
            match_response_status=dict(default=[401], type='list'),
            match_response_origin=dict(default=True, type='bool'),
            action_mode=dict(default='ban', choices=['ban', 'simulate'], type='str'),
            action_timeout=dict(default=86400, type='int'),
            action_body=dict(default=DEFAULT_ERROR_MSG, type='str'),
            action_content_type=dict(default='text/xml')
        )
    )

    account_email = module.params['account_email']
    account_api_token = module.params['account_api_token']
    zone = module.params['zone_identifier']
    state = module.params['state']
    description = module.params['description']
    disabled = module.params['disabled']
    threshold = module.params['threshold']
    period = module.params['period']

    # Had to sanitize to ensure list is made up of integers (instead of str)
    match_response_status_sanitized = [int(x) for x in
                                       module.params['match_response_status']]

    # definition for match is defined on the cloudflare API v4 documentation
    match = dict(
                request=dict(
                    methods=module.params['match_method'],
                    schemes=module.params['match_schemes'],
                    url=module.params['match_url']),
                response=dict(
                    status=match_response_status_sanitized,
                    origin_traffic=module.params['match_response_origin'])
                )
    # definition for action is defined on the cloudflare API v4 documentation
    action = dict(
                mode=module.params['action_mode'],
                timeout=module.params['action_timeout'],
                response=dict(
                    content_type=module.params['action_content_type'],
                    body=module.params['action_body'])
                )

    # API sanity checks

    # Min and maximum parameter checks, based on API specs
    if threshold < THRESHOLD_MIN or threshold > THRESHOLD_MAX:
        module.fail_json(msg="Threshold must be between %s and %s" % (
            str(THRESHOLD_MIN),
            str(THRESHOLD_MAX)))
    if period < PERIOD_MIN or period > PERIOD_MAX:
        module.fail_json(msg="Period must be between %s and %s" % (
            str(PERIOD_MIN),
            str(PERIOD_MAX)))

    # Bomb out if cloudflare module is not installed
    if not HAS_CF:
        module.fail_json(msg="cloudflare pip module required")

    # Meat and potatoes
    try:
        cf = CF_API(zone, account_email, account_api_token)
        results = cf.create_ratelimit(description,
                                      disabled,
                                      threshold,
                                      period,
                                      match,
                                      action)
        if not results:
            module.exit_json(changed=False)
        module.exit_json(changed=True, results=results)
    except CloudFlare.exceptions.CloudFlareAPIError as e:
        module.fail_json(msg='Errr %s' % str(e))
    except UserWarning as e:
        module.fail_json(msg='Parameter issue, %s' % e)

if __name__ == '__main__':
    main()

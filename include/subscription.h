#pragma once

#include <map>
#include <mutex>
#include <set>
#include <string>
#include <vector>

struct Subscription
{
    std::map<std::string, std::string> args;
};

std::string build_subscribe_message_json(const Subscription& sub);
std::string subscription_key(const Subscription& sub);

class RuntimeSubscriptionRegistry
{
public:
    void                      mark_existing(const std::vector<Subscription>& subs);
    void                      request(std::string symbol, std::string channel);
    std::vector<Subscription> take_pending();

private:
    std::mutex                _mutex;
    std::set<std::string>     _known;
    std::vector<Subscription> _pending;
};

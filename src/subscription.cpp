#include "subscription.h"

#include <string_view>
#include <utility>

namespace
{

std::string json_escape(std::string_view input)
{
	std::string escaped;
	escaped.reserve(input.size() + 8);
	for (const char ch : input)
	{
		switch (ch)
		{
		case '\"':
			escaped += "\\\"";
			break;
		case '\\':
			escaped += "\\\\";
			break;
		case '\b':
			escaped += "\\b";
			break;
		case '\f':
			escaped += "\\f";
			break;
		case '\n':
			escaped += "\\n";
			break;
		case '\r':
			escaped += "\\r";
			break;
		case '\t':
			escaped += "\\t";
			break;
		default:
			escaped += ch;
			break;
		}
	}
	return escaped;
}

}  // namespace

std::string build_subscribe_message_json(const std::vector<Subscription>& subs)
{
	std::string message = R"({"op":"subscribe","args":[)";
	for (size_t i = 0; i < subs.size(); ++i)
	{
		if (i > 0)
		{
			message += ",";
		}
		message += "{";
		size_t field_index = 0;
		for (const auto& [key, value] : subs[i].args)
		{
			if (field_index > 0)
			{
				message += ",";
			}
			message += "\"";
			message += json_escape(key);
			message += "\":\"";
			message += json_escape(value);
			message += "\"";
			++field_index;
		}
		message += "}";
	}
	message += "]}";
	return message;
}

std::string subscription_key(const Subscription& sub)
{
	const auto channel_it = sub.args.find("channel");
	const auto inst_it = sub.args.find("instId");
	const std::string channel = channel_it == sub.args.end() ? "" : channel_it->second;
	const std::string inst_id = inst_it == sub.args.end() ? "" : inst_it->second;
	return channel + ":" + inst_id;
}

void RuntimeSubscriptionRegistry::mark_existing(const std::vector<Subscription>& subs)
{
	std::lock_guard<std::mutex> lock(_mutex);
	for (const auto& sub : subs)
	{
		_known.insert(subscription_key(sub));
	}
}

void RuntimeSubscriptionRegistry::request(std::string symbol, std::string channel)
{
	if (symbol.empty() || channel.empty())
	{
		return;
	}

	Subscription sub;
	sub.args["channel"] = std::move(channel);
	sub.args["instId"] = std::move(symbol);
	const auto key = subscription_key(sub);

	std::lock_guard<std::mutex> lock(_mutex);
	if (_known.insert(key).second)
	{
		_pending.push_back(std::move(sub));
	}
}

std::vector<Subscription> RuntimeSubscriptionRegistry::take_pending()
{
	std::lock_guard<std::mutex> lock(_mutex);
	std::vector<Subscription> out;
	out.swap(_pending);
	return out;
}

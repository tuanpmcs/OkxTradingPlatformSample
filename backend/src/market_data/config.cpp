#include "market_data/config.hpp"

#include "common/logger.hpp"

#include <stdexcept>

namespace
{

template <typename T>
std::optional<T> get_optional(const YAML::Node& node, const std::string& key)
{
	const auto child = node[key];
	if (!child)
	{
		return std::nullopt;
	}

	try
	{
		return child.as<T>();
	}
	catch (const YAML::Exception& e)
	{
		LOG_STREAM_ERROR("Failed to parse config key '" << key << "': " << e.what());
		return std::nullopt;
	}
}

template <typename T>
T get_required(const YAML::Node& node, const std::string& key)
{
	const auto child = node[key];
	if (!child)
	{
		throw std::runtime_error("Missing required config key: " + key);
	}

	try
	{
		return child.as<T>();
	}
	catch (const YAML::Exception& e)
	{
		throw std::runtime_error("Failed to parse required config key '" + key + "': " + e.what());
	}
}

}  // namespace

YAML::Node YamlConfig::load(const std::string& config_file)
{
	try
	{
		return YAML::LoadFile(config_file);
	}
	catch (const YAML::Exception& e)
	{
		LOG_STREAM_ERROR("Failed to load config file: " << e.what());
		return YAML::Node();
	}
}

YAML::Node YamlConfig::load_from_string(const std::string_view& config_content)
{
	try
	{
		return YAML::Load(std::string(config_content));
	}
	catch (const YAML::Exception& e)
	{
		LOG_STREAM_ERROR("Failed to load config from string: " << e.what());
		return YAML::Node();
	}
}

Subscription parse_subscription(const YAML::Node& node)
{
	Subscription sub;
	if (!node.IsMap())
	{
		throw std::runtime_error("Subscription entry must be a map/object.");
	}

	for (const auto& item : node)
	{
		const auto key = item.first.as<std::string>();
		const auto value = item.second.as<std::string>();
		sub.args[key] = value;
	}

	if (sub.args.find("channel") == sub.args.end())
	{
		throw std::runtime_error("Subscription entry is missing required key: channel");
	}

	return sub;
}

WebSocketEndpoint parse_websocket_endpoint(const YAML::Node& node)
{
	WebSocketEndpoint ep;
	ep.ws_url = get_required<std::string>(node, "ws_url");

	if (const auto subs_node = node["subscriptions"])
	{
		for (const auto& sub_node : subs_node)
		{
			ep.subscriptions.push_back(parse_subscription(sub_node));
		}
	}

	return ep;
}

NetworkConfig parse_network_config(const YAML::Node& node)
{
	NetworkConfig cfg;
	cfg.forced_ip = get_optional<std::string>(node, "forced_ip").value_or("");
	cfg.reconnect_ms = get_optional<int>(node, "reconnect_ms").value_or(100);
	cfg.ping_interval_ms = get_optional<int>(node, "ping_interval_ms").value_or(100);
	cfg.stale_timeout_ms = get_optional<int>(node, "stale_timeout_ms").value_or(100);
	cfg.pong_timeout_ms = get_optional<int>(node, "pong_timeout_ms").value_or(100);
	return cfg;
}

WebSocketEndpointConfig parse_websocket_endpoint_config(const YAML::Node& node)
{
	WebSocketEndpointConfig cfg;
	if (const auto public_node = node["public_endpoint"])
	{
		cfg.public_endpoint = parse_websocket_endpoint(public_node);
	}
	if (const auto business_node = node["business_endpoint"])
	{
		cfg.business_endpoint = parse_websocket_endpoint(business_node);
	}
	return cfg;
}

OkxConfig from(const YAML::Node& root)
{
	try
	{
		OkxConfig config;
		config.exchange = get_required<std::string>(root, "exchange");
		config.network = parse_network_config(root["network"]);
		config.websocket_endpoint = parse_websocket_endpoint_config(root["websocket_endpoint"]);
		return config;
	}
	catch (const YAML::Exception& e)
	{
		throw std::runtime_error(std::string("Failed to parse OkxConfig: ") + e.what());
	}
}

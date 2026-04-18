#pragma once

#include "subscription.h"

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <yaml-cpp/yaml.h>

struct WebSocketEndpoint
{
	std::string				  ws_url;
	std::vector<Subscription> subscriptions;
};

struct NetworkConfig
{
	std::optional<std::string> forced_ip;
	int						   reconnect_ms;
	int						   ping_interval_ms;
	int						   stale_timeout_ms;
	int						   pong_timeout_ms;
};

struct WebSocketEndpointConfig
{
	std::optional<WebSocketEndpoint> public_endpoint;
	std::optional<WebSocketEndpoint> business_endpoint;
};

struct OkxConfig
{
	std::string				exchange;
	NetworkConfig			network;
	WebSocketEndpointConfig websocket_endpoint;
};

class YamlConfig
{
public:
	static YAML::Node load(const std::string& config_file);
	static YAML::Node load_from_string(const std::string_view& config_content);
};

Subscription parse_subscription(const YAML::Node& node);
WebSocketEndpoint parse_websocket_endpoint(const YAML::Node& node);
NetworkConfig parse_network_config(const YAML::Node& node);
WebSocketEndpointConfig parse_websocket_endpoint_config(const YAML::Node& node);
OkxConfig from(const YAML::Node& root);

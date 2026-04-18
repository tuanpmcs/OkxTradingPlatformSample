#include "tls_client.h"

#include <boost/beast/core/flat_buffer.hpp>
#include <openssl/err.h>

#include <chrono>
#include <exception>
#include <sstream>

namespace ssl = boost::asio::ssl;
namespace beast = boost::beast;
namespace websocket = boost::beast::websocket;

std::string TlsClient::make_error_message(const std::string& prefix, const boost::system::error_code& ec)
{
	std::ostringstream oss;
	oss << prefix << ": [" << ec.value() << "] " << ec.message();
	return oss.str();
}

bool TlsClient::is_timeout_error(const boost::system::error_code& ec) noexcept
{
	return ec == boost::asio::error::timed_out || ec == beast::error::timeout;
}

TlsClient::TlsClient()
	  : _ssl_context(ssl::context::tls_client), _resolver(_io_context)
{
	_ssl_context.set_default_verify_paths();
	_ssl_context.set_verify_mode(ssl::verify_peer);

	_ws_stream = std::make_unique<WebSocketStream>(_io_context, _ssl_context);
	_ws_stream->set_option(websocket::stream_base::timeout::suggested(beast::role_type::client));
	_ws_stream->set_option(websocket::stream_base::decorator(
			[](websocket::request_type& req) {
				req.set(
						boost::beast::http::field::user_agent,
						std::string(BOOST_BEAST_VERSION_STRING) + " tls-client");
			}));
}

TlsClient::~TlsClient()
{
	boost::system::error_code ec;
	if (_ws_stream && _ws_stream->is_open())
	{
		_ws_stream->close(websocket::close_code::normal, ec);
	}
}

TlsClient::Result TlsClient::connect(const std::string& host,
									 const std::string& port,
									 const std::string& target,
									 int				timeout_ms)
{
	try
	{
		_host = host;
		_port = port;
		_target = target;

		if (!_ws_stream)
		{
			_ws_stream = std::make_unique<WebSocketStream>(_io_context, _ssl_context);
		}

		boost::system::error_code ec;
		auto results = _resolver.resolve(_host, _port, ec);
		if (ec)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("Resolve timeout", ec)};
			}
			return {Status::ConnectionFailed, make_error_message("Resolve failed", ec)};
		}

		auto& tcp_stream = beast::get_lowest_layer(*_ws_stream);
		tcp_stream.expires_after(std::chrono::milliseconds(timeout_ms));
		tcp_stream.connect(results, ec);
		if (ec)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("TCP connect timeout", ec)};
			}
			return {Status::ConnectionFailed, make_error_message("TCP connect failed", ec)};
		}

		if (!SSL_set_tlsext_host_name(_ws_stream->next_layer().native_handle(), _host.c_str()))
		{
			boost::system::error_code ssl_ec{
					static_cast<int>(::ERR_get_error()),
					boost::asio::error::get_ssl_category()};
			return {Status::HandshakeFailed, make_error_message("SNI setup failed", ssl_ec)};
		}

		_ws_stream->next_layer().handshake(ssl::stream_base::client, ec);
		if (ec)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("TLS handshake timeout", ec)};
			}
			return {Status::HandshakeFailed, make_error_message("TLS handshake failed", ec)};
		}

		tcp_stream.expires_never();
		return {Status::Success, "TCP/TLS connect success"};
	}
	catch (const std::exception& e)
	{
		return {Status::UnknownError, std::string("connect exception: ") + e.what()};
	}
}

TlsClient::Result TlsClient::handshake(const std::string& host, int timeout_ms)
{
	try
	{
		if (!_ws_stream)
		{
			return {Status::HandshakeFailed, "WebSocket stream is not initialized"};
		}

		boost::system::error_code ec;
		auto&					  tcp_stream = _ws_stream->next_layer().next_layer();
		tcp_stream.expires_after(std::chrono::milliseconds(timeout_ms));

		const std::string effective_host = host.empty() ? _host : host;
		_ws_stream->handshake(effective_host, _target, ec);
		if (ec)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("WebSocket handshake timeout", ec)};
			}
			return {Status::HandshakeFailed, make_error_message("WebSocket handshake failed", ec)};
		}

		tcp_stream.expires_never();
		return {Status::Success, "WebSocket handshake success"};
	}
	catch (const std::exception& e)
	{
		return {Status::UnknownError, std::string("handshake exception: ") + e.what()};
	}
}

TlsClient::Result TlsClient::write(const std::string& data, int timeout_ms)
{
	try
	{
		if (!_ws_stream || !_ws_stream->is_open())
		{
			return {Status::WriteFailed, "WebSocket is not open"};
		}

		boost::system::error_code ec;
		auto&					  tcp_stream = _ws_stream->next_layer().next_layer();
		tcp_stream.expires_after(std::chrono::milliseconds(timeout_ms));

		_ws_stream->text(true);
		_ws_stream->write(boost::asio::buffer(data), ec);
		if (ec)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("Write timeout", ec)};
			}
			return {Status::WriteFailed, make_error_message("Write failed", ec)};
		}

		tcp_stream.expires_never();
		return {Status::Success, "Write success"};
	}
	catch (const std::exception& e)
	{
		return {Status::UnknownError, std::string("write exception: ") + e.what()};
	}
}

TlsClient::Result TlsClient::read(std::string& response, int timeout_ms)
{
	try
	{
		response.clear();
		if (!_ws_stream || !_ws_stream->is_open())
		{
			return {Status::ReadFailed, "WebSocket is not open"};
		}

		beast::flat_buffer		  buffer;
		boost::system::error_code ec;
		auto&					  tcp_stream = _ws_stream->next_layer().next_layer();
		tcp_stream.expires_after(std::chrono::milliseconds(timeout_ms));

		_ws_stream->read(buffer, ec);
		if (ec == websocket::error::closed)
		{
			return {Status::Closed, "WebSocket closed by peer"};
		}
		if (ec)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("Read timeout", ec)};
			}
			return {Status::ReadFailed, make_error_message("Read failed", ec)};
		}

		tcp_stream.expires_never();
		response = beast::buffers_to_string(buffer.data());
		return {Status::Success, "Read success"};
	}
	catch (const std::exception& e)
	{
		return {Status::UnknownError, std::string("read exception: ") + e.what()};
	}
}

TlsClient::Result TlsClient::close(int timeout_ms)
{
	try
	{
		if (!_ws_stream)
		{
			return {Status::Closed, "WebSocket stream is not initialized"};
		}
		if (!_ws_stream->is_open())
		{
			return {Status::Closed, "WebSocket already closed"};
		}

		boost::system::error_code ec;
		auto&					  tcp_stream = _ws_stream->next_layer().next_layer();
		tcp_stream.expires_after(std::chrono::milliseconds(timeout_ms));

		_ws_stream->close(websocket::close_code::normal, ec);
		if (ec && ec != websocket::error::closed)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("Close timeout", ec)};
			}
			return {Status::UnknownError, make_error_message("Close failed", ec)};
		}

		tcp_stream.expires_never();
		return {Status::Success, "Close success"};
	}
	catch (const std::exception& e)
	{
		return {Status::UnknownError, std::string("close exception: ") + e.what()};
	}
}

bool TlsClient::is_open() const noexcept
{
	return _ws_stream && _ws_stream->is_open();
}

#pragma once

#include <boost/asio.hpp>
#include <boost/asio/ssl.hpp>
#include <boost/beast.hpp>
#include <boost/beast/ssl.hpp>
#include <boost/beast/websocket.hpp>

#include <memory>
#include <string>

class TlsClient
{
public:
	enum class Status
	{
		Success,
		HandshakeFailed,
		ConnectionFailed,
		ReadFailed,
		WriteFailed,
		Timeout,
		Closed,
		UnknownError
	};

	struct [[nodiscard]] Result
	{
		Status		status{Status::UnknownError};
		std::string message;

		bool ok() const noexcept
		{
			return status == Status::Success;
		}
	};

public:
	TlsClient();
	virtual ~TlsClient();

	[[nodiscard]] Result connect(const std::string& host,
								 const std::string& port,
								 const std::string& target,
								 int				timeout_ms);
	[[nodiscard]] Result handshake(const std::string& host, int timeout_ms);
	[[nodiscard]] Result write(const std::string& data, int timeout_ms);
	[[nodiscard]] Result read(std::string& response, int timeout_ms);
	[[nodiscard]] Result close(int timeout_ms);
	[[nodiscard]] bool is_open() const noexcept;

private:
	using tcp = boost::asio::ip::tcp;
	using WebSocketStream =
			boost::beast::websocket::stream<boost::beast::ssl_stream<boost::beast::tcp_stream>>;

	static std::string make_error_message(const std::string& prefix, const boost::system::error_code& ec);
	static bool is_timeout_error(const boost::system::error_code& ec) noexcept;

private:
	boost::asio::io_context			 _io_context;
	boost::asio::ssl::context		 _ssl_context;
	tcp::resolver					 _resolver;
	std::unique_ptr<WebSocketStream> _ws_stream;

	std::string _host;
	std::string _port;
	std::string _target;
};

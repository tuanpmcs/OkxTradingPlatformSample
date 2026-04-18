#include "grpc_stream.h"

#include <algorithm>
#include <stdexcept>
#include <string>

bool GrpcTickHub::Subscriber::wait_pop(StreamRecord& event, std::chrono::milliseconds timeout)
{
	std::unique_lock<std::mutex> lock(mutex);
	cv.wait_for(lock, timeout, [this]() {
		return closed || !queue.empty();
	});

	if (queue.empty())
	{
		return false;
	}

	event = std::move(queue.front());
	queue.pop_front();
	return true;
}

std::shared_ptr<GrpcTickHub::Subscriber> GrpcTickHub::add_subscriber()
{
	auto						subscriber = std::make_shared<Subscriber>();
	std::lock_guard<std::mutex> lock(_mutex);
	_subscribers.push_back(subscriber);
	return subscriber;
}

void GrpcTickHub::remove_subscriber(const std::shared_ptr<Subscriber>& target)
{
	std::lock_guard<std::mutex> lock(_mutex);
	_subscribers.erase(
			std::remove(_subscribers.begin(), _subscribers.end(), target),
			_subscribers.end());
}

void GrpcTickHub::broadcast(const StreamRecord& event)
{
	std::vector<std::shared_ptr<Subscriber>> snapshot;
	{
		std::lock_guard<std::mutex> lock(_mutex);
		snapshot = _subscribers;
	}

	for (auto& subscriber : snapshot)
	{
		{
			std::lock_guard<std::mutex> lock(subscriber->mutex);
			subscriber->queue.push_back(event);
			if (subscriber->queue.size() > 1024)
			{
				subscriber->queue.pop_front();
			}
		}
		subscriber->cv.notify_one();
	}
}

void GrpcTickHub::shutdown()
{
	std::vector<std::shared_ptr<Subscriber>> snapshot;
	{
		std::lock_guard<std::mutex> lock(_mutex);
		snapshot = _subscribers;
		_subscribers.clear();
	}

	for (auto& subscriber : snapshot)
	{
		{
			std::lock_guard<std::mutex> lock(subscriber->mutex);
			subscriber->closed = true;
		}
		subscriber->cv.notify_all();
	}
}

MarketDataServiceImpl::MarketDataServiceImpl(
		GrpcTickHub& hub,
		RuntimeSubscriptionRegistry* runtime_subscriptions)
	  : _hub(hub), _runtime_subscriptions(runtime_subscriptions)
{
}

grpc::Status MarketDataServiceImpl::Subscribe(grpc::ServerContext* context,
											  const marketstream::SubscribeRequest* request,
											  grpc::ServerWriter<marketstream::Tick>* writer)
{
	auto			  subscriber = _hub.add_subscriber();
	const std::string requested_channel = request ? request->channel() : "";
	const std::string requested_symbol = request ? request->symbol() : "";
	if (_runtime_subscriptions && !requested_channel.empty() && !requested_symbol.empty())
	{
		_runtime_subscriptions->request(requested_symbol, requested_channel);
	}

	while (!context->IsCancelled())
	{
		StreamRecord event;
		if (!subscriber->wait_pop(event, std::chrono::milliseconds(250))) continue;

		if (!requested_channel.empty())
		{
			const auto it = event.fields.find("channel");
			if (it == event.fields.end() || it->second != requested_channel) continue;
		}

		if (!requested_symbol.empty())
		{
			const auto it = event.fields.find("instId");
			if (it == event.fields.end() || it->second != requested_symbol) continue;
		}

		marketstream::Tick tick;
		tick.set_ts(event.ts_ms);
		tick.set_price(event.price);
		tick.set_change(event.change);
		tick.set_source(event.source);
		tick.set_raw_json(event.raw_json);
		for (const auto& [k, v] : event.fields)
		{
			(*tick.mutable_fields())[k] = v;
		}
		for (const auto& field_name : event.changed_fields)
		{
			tick.add_changed_fields(field_name);
		}

		if (!writer->Write(tick)) break;
	}

	_hub.remove_subscriber(subscriber);
	return grpc::Status::OK;
}

GrpcServerRuntime::GrpcServerRuntime(MarketDataServiceImpl& service, unsigned short port)
	  : _service(service), _port(port)
{
}

GrpcServerRuntime::~GrpcServerRuntime()
{
	stop();
}

void GrpcServerRuntime::start()
{
	grpc::ServerBuilder builder;
	const std::string	address = "0.0.0.0:" + std::to_string(_port);
	builder.AddListeningPort(address, grpc::InsecureServerCredentials());
	builder.RegisterService(&_service);
	_server = builder.BuildAndStart();
	if (!_server)
	{
		throw std::runtime_error("Failed to start gRPC server on " + address);
	}

	_thread = std::thread([this]() {
		_server->Wait();
	});
}

void GrpcServerRuntime::stop()
{
	if (_stopped) return;
	_stopped = true;

	if (_server) _server->Shutdown();
	if (_thread.joinable()) _thread.join();
}

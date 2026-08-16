import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../api/fms_api.dart';
import '../../api/fms_api_client.dart';
import '../../api/fms_models.dart';

class OrderPage extends StatefulWidget {
  const OrderPage({super.key, required this.api, required this.requestedBy});

  final FmsApi api;
  final String requestedBy;

  @override
  State<OrderPage> createState() => _OrderPageState();
}

class _ProductOption {
  const _ProductOption({
    required this.productCode,
    required this.name,
    required this.availableQuantity,
  });

  final String productCode;
  final String name;
  final int availableQuantity;

  String get label => '$name · $productCode';
}

class _OrderLineEntry {
  _OrderLineEntry(this.product) : quantity = TextEditingController(text: '1');

  final _ProductOption product;
  final TextEditingController quantity;

  void dispose() => quantity.dispose();
}

class _OrderPageState extends State<OrderPage> {
  final _search = TextEditingController();
  final List<_OrderLineEntry> _lines = [];
  late Future<List<_ProductOption>> _products;
  String _priority = 'normal';
  bool _allowPartial = false;
  bool _submitting = false;
  String? _submissionKey;
  OutboundOrderDto? _result;
  String? _error;

  @override
  void initState() {
    super.initState();
    _products = _loadProducts();
    _search.addListener(_searchChanged);
  }

  @override
  void dispose() {
    _search
      ..removeListener(_searchChanged)
      ..dispose();
    for (final line in _lines) {
      line.dispose();
    }
    super.dispose();
  }

  Future<List<_ProductOption>> _loadProducts() async {
    final lots = await widget.api.listInventory();
    final quantities = <String, int>{};
    final names = <String, String>{};
    for (final lot in lots) {
      quantities.update(
        lot.productCode,
        (value) => value + lot.availableQty - lot.reservedQty,
        ifAbsent: () => lot.availableQty - lot.reservedQty,
      );
      names[lot.productCode] = lot.itemName ?? lot.productCode;
    }
    final products = [
      for (final entry in quantities.entries)
        _ProductOption(
          productCode: entry.key,
          name: names[entry.key]!,
          availableQuantity: entry.value,
        ),
    ]..sort((a, b) => a.productCode.compareTo(b.productCode));
    return List.unmodifiable(products);
  }

  void _searchChanged() => setState(() {});

  _ProductOption? _match(List<_ProductOption> products) {
    final query = _search.text.trim().toLowerCase();
    if (query.isEmpty) return null;
    for (final product in products) {
      if (product.productCode.toLowerCase().contains(query) ||
          product.name.toLowerCase().contains(query)) {
        return product;
      }
    }
    return null;
  }

  void _addProduct(_ProductOption product) {
    if (_lines.any((line) => line.product.productCode == product.productCode)) {
      setState(() => _error = '이미 추가한 상품입니다.');
      return;
    }
    setState(() {
      _lines.add(_OrderLineEntry(product));
      _search.clear();
      _result = null;
      _error = null;
      _submissionKey = null;
    });
  }

  void _removeLine(int index) {
    setState(() {
      _lines.removeAt(index).dispose();
      _result = null;
      _submissionKey = null;
    });
  }

  void _intentChanged(VoidCallback change) {
    setState(() {
      change();
      _result = null;
      _submissionKey = null;
    });
  }

  Future<void> _submit() async {
    final quantities = _lines
        .map((line) => int.tryParse(line.quantity.text.trim()))
        .toList(growable: false);
    if (_lines.isEmpty ||
        quantities.any((quantity) => quantity == null || quantity <= 0)) {
      setState(() => _error = '상품과 1 이상의 수량을 확인하세요.');
      return;
    }
    final key = _submissionKey ??=
        'control-ui-order-${DateTime.now().microsecondsSinceEpoch}';
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final result = await widget.api.createOutboundOrder(
        OutboundOrderRequestDto(
          externalReference: null,
          requester: widget.requestedBy,
          priority: _priority,
          allowPartialFulfillment: _allowPartial,
          lines: [
            for (var index = 0; index < _lines.length; index += 1)
              OutboundOrderLineDto(
                productCode: _lines[index].product.productCode,
                quantity: quantities[index]!,
              ),
          ],
        ),
        idempotencyKey: key,
      );
      if (!mounted) return;
      setState(() => _result = result);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = fmsApiUserMessage(error));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<List<_ProductOption>>(
    future: _products,
    builder: (context, snapshot) {
      if (snapshot.connectionState != ConnectionState.done) {
        return const Center(child: CircularProgressIndicator());
      }
      if (snapshot.hasError) {
        return Center(child: Text(fmsApiUserMessage(snapshot.error!)));
      }
      final products = snapshot.data!;
      final match = _match(products);
      return ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text('출고 주문', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 8),
          const Text('상품과 수량을 입력하면 재고와 운영 위치에서 작업을 자동 계획합니다.'),
          const SizedBox(height: 24),
          TextField(
            key: const Key('product-search'),
            controller: _search,
            decoration: const InputDecoration(
              labelText: '상품 코드 또는 이름 검색',
              prefixIcon: Icon(Icons.search),
              border: OutlineInputBorder(),
            ),
          ),
          if (match != null) ...[
            const SizedBox(height: 8),
            Text(match.label),
            Text('현재 가용 ${match.availableQuantity}'),
          ],
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton.icon(
              onPressed: match == null ? null : () => _addProduct(match),
              icon: const Icon(Icons.add),
              label: const Text('상품 추가'),
            ),
          ),
          const SizedBox(height: 20),
          for (var index = 0; index < _lines.length; index += 1)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    Expanded(child: Text(_lines[index].product.label)),
                    SizedBox(
                      width: 120,
                      child: TextField(
                        key: Key('quantity-${index + 1}'),
                        controller: _lines[index].quantity,
                        keyboardType: TextInputType.number,
                        inputFormatters: [
                          FilteringTextInputFormatter.digitsOnly,
                        ],
                        decoration: const InputDecoration(labelText: '수량'),
                        onChanged: (_) => _submissionKey = null,
                      ),
                    ),
                    IconButton(
                      tooltip: '상품 삭제',
                      onPressed: () => _removeLine(index),
                      icon: const Icon(Icons.delete_outline),
                    ),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              const Text('우선순위'),
              ChoiceChip(
                label: const Text('일반'),
                selected: _priority == 'normal',
                onSelected: (_) => _intentChanged(() => _priority = 'normal'),
              ),
              ChoiceChip(
                label: const Text('긴급'),
                selected: _priority == 'critical',
                onSelected: (_) => _intentChanged(() => _priority = 'critical'),
              ),
            ],
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('부분 출고 허용'),
            subtitle: const Text('재고가 부족하면 가용 수량을 예약하고 미출고 수량을 남깁니다.'),
            value: _allowPartial,
            onChanged: (value) => _intentChanged(() => _allowPartial = value),
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _submitting ? null : _submit,
            child: Text(_submitting ? '제출 중…' : '주문 제출'),
          ),
          if (_error != null) ...[
            const SizedBox(height: 16),
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
          if (_result case final result?) ...[
            const SizedBox(height: 20),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      result.jobCode,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      '출고 가능 ${result.fulfillableQuantity}/요청 ${result.requestedQuantity}',
                    ),
                    Text('미출고 ${result.outstandingQuantity}'),
                  ],
                ),
              ),
            ),
          ],
        ],
      );
    },
  );
}

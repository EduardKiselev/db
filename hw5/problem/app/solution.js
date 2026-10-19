// Заполняйте TODO. c — переданная база; функции выполняют реальные запросы MongoDB.
// Служебный lab.js менять не требуется. Контракты и порядок опытов — в Задание.md.
globalThis.installValidator = async c => {
  return c.runCommand({
    collMod: "products",
    validator: {
      $jsonSchema: {
      bsonType: "object",
      required: ["name", "price", "category", "variants"],
      properties: {
        _id: { bsonType: 'string' },
        name: { bsonType: "string" },
        category: { bsonType: "string" },
        price: { bsonType: "decimal", minimum: 0 },
        variants: {
          bsonType: 'array',
          items: {
            bsonType: 'object',
            required: ['size', 'stock'],
            properties: {
              size: { bsonType: 'string' },
              stock: { bsonType: ['int', 'long'], minimum: 0 }
            }
          }
        }

      }
      }
    },
    validationAction: "error",
    validationLevel: "strict"
    })
};

// Возврат: Promise массива полных Product; порядок _id ASC; [] при отсутствии.
globalThis.searchProducts = async (c, {category, size, qty}) => {
  return c.products.find({
    category: category,
    variants: { $elemMatch: { size: size, stock: { $gte: NumberInt(qty) } } }
  }).sort({ _id: 1 }).toArray();
};

// Технический helper: верните MongoDB cursor с фильтром, сортировкой и limit.
// Один и тот же запрос используется для результата и explain в опыте с индексом.
globalThis.historyCursor = (c, {userId, status}) => {
  return c.orders.find({
    userId: userId,
    status: status
  }).sort({ createdAt: -1, _id: 1 }).limit(20);
};
globalThis.history = async (c, input) => historyCursor(c, input).toArray();

// Порядок полей по правилу ESR: Equality (userId, status) — равенство из фильтра,
// Sort (createdAt: -1, _id: 1) — точно в порядке сортировки запроса, Range — пуст.
// Благодаря этому обход индекса уже выдаёт документы в нужном порядке,
// и отдельная стадия SORT не требуется.
globalThis.historyIndex = { userId: 1, status: 1, createdAt: -1, _id: 1 };
// Если добавили hint в historyCursor, измените флаг на true.
globalThis.usesHistoryHint = false;

// Возврат: Promise массива {sku, name, qty, revenue}; revenue — Decimal128.
globalThis.report = async (c, from, to) => {
  return c.orders.aggregate([
    { $match: { status: 'paid', createdAt: { $gte: from, $lt: to } } },
    { $unwind: '$items' },
    { $group: {
        _id: '$items.sku',
        qty: { $sum: '$items.qty' },
        revenue: { $sum: { $multiply: ['$items.qty', '$items.price'] } }
    } },
        { $lookup: { from: 'products', localField: '_id', foreignField: '_id', as: 'product' } },
          { $unwind: '$product' },
    { $project: { _id: 0, sku: '$_id', name: '$product.name', qty: 1, revenue: 1 } },
    { $sort: { revenue: -1, sku: 1 } },
    { $limit: 5 }
  ]).toArray();  
};

// request: {operationId, userId, items:[{sku,size,qty},{sku,size,qty}]}.
// Входы соответствуют контракту задания. Два SKU различны; порядок items значим.
// Возврат: Promise созданного или ранее сохранённого Order.
// При отказе: throw HWError('ITEM_UNAVAILABLE') или HWError('REQUEST_CONFLICT').
// Сообщение ошибки свободное; сценарий проверяет только error.code.
// transaction(body) предоставлена: body получает c — базу в активной сессии.
// Все операции покупки внутри body выполняйте через этот c.
globalThis.purchase = async (request, trace = () => {}) => {
  const { operationId, userId, items } = request;
  return transaction(async c => {

    // 1. Обработка повторного запроса: _id заказа равен operationId,
    const existing = await c.orders.findOne({ _id: operationId });
    if (existing) {
      const sameRequest =
        Number(existing.userId) === Number(userId) &&
        Array.isArray(existing.items) &&
        existing.items.length === items.length &&
        existing.items.every((saved, i) =>
          saved.sku === items[i].sku &&
          saved.size === items[i].size &&
          Number(saved.qty) === Number(items[i].qty));
      if (sameRequest) return existing; // подтверждённая покупка — вернуть как есть
      throw HWError('REQUEST_CONFLICT', 'operationId уже использован с другим заказом');
    }

    // 2. Списание остатков.
    //    matchedCount == 0 означает, что товара, размера или остатка нет.
    //    $inc обязательно через NumberInt — иначе stock стал бы double
    const orderItems = [];
    for (const item of items) {
      const qty = NumberInt(item.qty);
      const r = await c.products.updateOne(
        { _id: item.sku, variants: { $elemMatch: { size: item.size, stock: { $gte: qty } } } },
        { $inc: { 'variants.$.stock': NumberInt(-item.qty) } }
      );
      // Фиксируем настоящую попытку: первое списание успевает пройти до abort.
      trace({ event: 'update_inside_transaction', sku: item.sku, matched: r.matchedCount, modified: r.modifiedCount });
      if (r.matchedCount !== 1 || r.modifiedCount !== 1) {
        // Исключение внутри body приводит оболочку transaction() к abortTransaction.
        throw HWError('ITEM_UNAVAILABLE', 'Нет товара, размера или достаточного остатка: ' + item.sku + '/' + item.size);
      }
      // Цена позиции — факт на момент покупки, берётся из каталога внутри
      // той же транзакции (readConcern snapshot) и сохраняется в заказ.
      const product = await c.products.findOne({ _id: item.sku }, { price: 1 });
      orderItems.push({ sku: item.sku, size: item.size, qty: qty, price: product.price });
    }

    // 3. Создаем заказ
    const order = {
      _id: operationId,
      userId: NumberInt(userId),
      createdAt: new Date(),
      status: 'created',
      items: orderItems
    };
    await c.orders.insertOne(order);
    return order; // успешный возврат body приводит оболочку к commitTransaction
  });
};

// Используйте именно переданный c: он связан с одним MongoDB-клиентом опыта.
// writeProbe: сохранить {_id:id, message} в c.probe с majority и j:true.
// Возврат — результат записи с acknowledged:true. Повтор вызова с тем же id
// должен быть безопасен: оболочка опыта может повторить запись после ошибки связи.
globalThis.writeProbe = async (c, id, message) => {
  // upsert + $set делает повтор безопасным: оболочка опыта может повторить
  // запись после потери ответа при переключении primary, и это не создаст
  // второй документ и не изменит уже подтверждённое сообщение.
  return c.probe.updateOne(
    { _id: id },
    { $set: { message: message } },
    { upsert: true, writeConcern: { w: 'majority', j: true, wtimeout: 5000 } }
  );
};
// Возврат — документ c.probe с указанным _id либо null.
globalThis.readProbe = async (c, id) => {
  return c.probe.findOne({ _id: id });
};

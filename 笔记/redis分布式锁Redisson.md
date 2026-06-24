# redis分布式锁Redisson

## 	底层实现

​		需要**setnx方法**获取锁才能进行操作，**lua脚本**保证一致性

```
获取锁：
	SET lock value NX EX 10
释放锁：
	DEL lock
```

## 	过期时间

​		为了确保线程能够完成业务，一般通过业务执行时间预估过期时间，或者给锁续期。

​		redission在这里引入了**watch dog**机制，在线程占有锁的情况下，会开辟一个线程来监听，每隔释放时间的1/3给线程续期。

```
public void redisLock() throws InterruptionException{
    Rlock lock = RedissonCLient.getLock("lock");
    boolean isLock = lock.tryLock(10,TimeUnit.SECONDS);/这里的10指最大等待时间，这段时间会一直请求获取锁
    if(isLOck){
       try{
            system.out.println("执行业务")；
       }
    }finally{
        	lock.unlock();
    }
}
```

## 	**可重入性**

​		同一线程可以重入获取锁。

​		原理：使用hash结构记录线程id和重入次数，也就是key=“lock”，value=“线程id，1”，当数字变为0时，这组hash值才会被删除，锁才会真正被释放。

## 	主从一致性

​		redisson不能解决主从一致性，可以用redisson提供的红锁解决，但是性能很低，如果有必要保证数据的一致性，可以采用zookeeper实现的分布式锁
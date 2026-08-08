package com.example.smsusbforwarder.data.db

import android.content.Context
import androidx.room.*
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "pending_messages")
data class PendingMessageEntity(@PrimaryKey val messageId: String, val payloadJson: String, val createdAt: Long, val expiresAt: Long, val attemptCount: Int = 0)

@Entity(tableName = "event_logs")
data class EventLogEntity(@PrimaryKey(autoGenerate = true) val id: Long = 0, val timestamp: Long, val category: String, val message: String)

@Dao
interface PendingMessageDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE) suspend fun insert(item: PendingMessageEntity): Long
    @Query("SELECT * FROM pending_messages WHERE expiresAt > :now ORDER BY createdAt LIMIT :limit") suspend fun ready(now: Long, limit: Int = 100): List<PendingMessageEntity>
    @Query("SELECT COUNT(*) FROM pending_messages WHERE expiresAt > :now") fun count(now: Long): Flow<Int>
    @Query("SELECT COUNT(*) FROM pending_messages") suspend fun totalCount(): Int
    @Query("UPDATE pending_messages SET attemptCount = :attempts WHERE messageId = :id") suspend fun updateAttempts(id: String, attempts: Int)
    @Query("DELETE FROM pending_messages WHERE messageId = :id") suspend fun delete(id: String)
    @Query("DELETE FROM pending_messages WHERE expiresAt <= :now") suspend fun deleteExpired(now: Long): Int
    @Query("DELETE FROM pending_messages") suspend fun clear()
    @Query("DELETE FROM pending_messages WHERE messageId IN (SELECT messageId FROM pending_messages ORDER BY createdAt ASC LIMIT :count)") suspend fun deleteOldest(count: Int)
}

@Dao
interface EventLogDao {
    @Insert suspend fun insert(item: EventLogEntity)
    @Query("SELECT * FROM event_logs ORDER BY timestamp DESC LIMIT 200") fun observe(): Flow<List<EventLogEntity>>
    @Query("DELETE FROM event_logs WHERE id NOT IN (SELECT id FROM event_logs ORDER BY timestamp DESC LIMIT 200)") suspend fun trim()
}

@Database(entities = [PendingMessageEntity::class, EventLogEntity::class], version = 1, exportSchema = true)
abstract class AppDatabase : RoomDatabase() {
    abstract fun pending(): PendingMessageDao
    abstract fun logs(): EventLogDao
    companion object { fun create(context: Context) = Room.databaseBuilder(context, AppDatabase::class.java, "sms_usb.db").fallbackToDestructiveMigration(false).build() }
}
